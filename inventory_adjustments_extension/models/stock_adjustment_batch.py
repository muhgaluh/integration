# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError

class StockAdjustmentBatch(models.Model):
    _name = 'stock.adjustment.batch'
    _description = 'Stock Adjustment Batch'
    _order = 'id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        states={'draft': [('readonly', False)]},
        default=lambda self: _('New')
    )
    user_id = fields.Many2one(
        'res.users',
        string='Responsible',
        default=lambda self: self.env.user,
        readonly=True
    )
    date = fields.Datetime(
        string='Date',
        default=fields.Datetime.now
    )
    reason = fields.Text(string='Reason')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Done'),
        ('cancel', 'Cancelled')
    ], string='Status', default='draft', readonly=True, copy=False)

    line_ids = fields.One2many(
        'stock.adjustment.batch.line',
        'batch_id',
        string='Adjustments'
    )

    is_stock_manager = fields.Boolean(
        string="Is Inventory Manager",
        compute='_compute_is_stock_manager'
    )
    # Tambahkan baris ini di dalam class StockAdjustmentBatch
    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        required=True,
        domain="[('usage', '=', 'internal')]",
        states={'draft': [('readonly', False)]},
        default=lambda self: self.env.ref('stock.stock_location_stock', raise_if_not_found=False)
    )

    @api.onchange('location_id')
    def _onchange_location_id(self):
        # Jika sudah ada baris produk, dan lokasi diganti
        if self.line_ids:
            # Command (5, 0, 0) artinya menghapus semua record relasi One2many
            self.line_ids = [(5, 0, 0)]
            return {
                'warning': {
                    'title': _("Peringatan: Lokasi Diubah!"),
                    'message': _("Semua baris perhitungan sebelumnya telah dihapus karena lokasi di Header diubah. Kuantitas sistem harus dihitung ulang untuk lokasi yang baru.")
                }
            }

    def _compute_is_stock_manager(self):
        for batch in self:
            batch.is_stock_manager = self.env.user.has_group('stock.group_stock_manager')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.adjustment.batch') or _('New')
        return super().create(vals_list)

    def action_request_approval(self):
        self.write({'state': 'in_progress'})
    
    def action_clear_lines(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("You can only clear lines on a batch in 'Draft' state."))
        # Ini akan menghapus semua baris yang terkait
        self.line_ids.unlink()
        return True
    # ----------------------------------------

    def action_set_counts_to_zero(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("You can only modify lines on a batch in 'Draft' state."))
        
        # Ini akan meng-update semua baris sekaligus
        if self.line_ids:
            self.line_ids.write({'counted_qty': 0})
        
        return True
    # ----------------------------------------

    def action_validate(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("You cannot validate a batch without any adjustment lines."))

        Quant = self.env['stock.quant']
        inventory_adjustments = []
        
        # Note the time before we start creating moves
        before_time = fields.Datetime.now()

        # Group lines by product and location
        for product, location in self.line_ids.mapped(lambda l: (l.product_id, l.location_id)):
            lines = self.line_ids.filtered(lambda l: l.product_id == product and l.location_id == location)
            
            # Auto-create lots if necessary for lines that don't have one
            for line in lines:
                if product.tracking != 'none' and not line.lot_id:
                    lot_name = self.name
                    lot_id = self.env['stock.lot'].search([('name', '=', lot_name), ('product_id', '=', product.id)], limit=1)
                    if not lot_id:
                        lot_id = self.env['stock.lot'].create({'name': lot_name, 'product_id': product.id, 'company_id': self.env.company.id})
                    line.lot_id = lot_id

            # Create a dictionary of {lot: counted_qty} from the batch lines
            counted_quants_data = {line.lot_id: line.counted_qty for line in lines}
            
            # Find all lots that currently exist in stock for this product/location
            existing_quants = Quant.search([('product_id', '=', product.id), ('location_id', '=', location.id)])
            existing_lots = existing_quants.mapped('lot_id')

            # Combine all lots (existing and newly counted) into one set to avoid duplicates
            all_lots_to_process = existing_lots | lines.mapped('lot_id')

            # Prepare the final inventory state for each lot
            for lot in all_lots_to_process:
                inventory_adjustments.append({
                    'product_id': product.id,
                    'location_id': location.id,
                    'lot_id': lot.id,
                    'inventory_quantity': counted_quants_data.get(lot, 0.0), # Use counted qty, or 0.0 if not in the batch
                })

        # Create all inventory adjustment records and then apply them
        if inventory_adjustments:
            quants = Quant.with_context(inventory_mode=True).create(inventory_adjustments)
            quants.action_apply_inventory()

            # Find the moves that were just created
            product_ids = self.line_ids.mapped('product_id').ids
            moves_to_update = self.env['stock.move'].search([
                ('product_id', 'in', product_ids),
                ('state', '=', 'done'),
                ('create_date', '>=', before_time)
            ])
            
            # Update the date and reference on the moves AND their move lines
            if moves_to_update:
                vals_to_write = {
                    'date': self.date,
                    'reference': self.name,
                }
                moves_to_update.write(vals_to_write)
                moves_to_update.mapped('move_line_ids').write({'date': self.date})

        self.write({'state': 'done'})
        return True