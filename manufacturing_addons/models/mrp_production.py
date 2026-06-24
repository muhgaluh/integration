from odoo import models, fields, api


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    production_status = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
        ('in_progress', 'In Progress'),
        ('to_close', 'To Close'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], compute='_compute_production_status')

    @api.depends('state')
    def _compute_production_status(self):
        for mo in self:

            if mo.state == 'draft':
                mo.production_status = 'draft'

            elif mo.state == 'confirmed':
                mo.production_status = 'confirmed'

            elif mo.state == 'progress':
                mo.production_status = 'in_progress'

            elif mo.state == 'to_close':
                mo.production_status = 'to_close'

            elif mo.state == 'done':
                mo.production_status = 'done'

            elif mo.state == 'cancel':
                mo.production_status = 'cancelled'


    # Ovveride Consume Tracking By Lots
    def _set_qty_producing(self):
        """
        Override Odoo standard.
        Untuk produk tracking by lot, otomatis isi qty_done
        sesuai quantity yang harus dikonsumsi.
        """

        res = super()._set_qty_producing()

        for production in self:

            if not production.product_qty:
                continue

            factor = production.qty_producing / production.product_qty

            for move in production.move_raw_ids.filtered(
                lambda m: m.state not in ('done', 'cancel')
                and m.product_id.tracking == 'lot'
            ):

                qty_to_consume = move.product_uom_qty * factor

                # Jika move line belum ada
                if not move.move_line_ids and qty_to_consume > 0:

                    self.env['stock.move.line'].create({
                        'move_id': move.id,
                        'product_id': move.product_id.id,
                        'product_uom_id': move.product_uom.id,
                        'location_id': move.location_id.id,
                        'location_dest_id': move.location_dest_id.id,
                        'qty_done': qty_to_consume,
                    })

                # Jika move line sudah ada
                if move.move_line_ids:

                    remaining = qty_to_consume

                    for line in move.move_line_ids:

                        if remaining <= 0:
                            line.qty_done = 0
                            continue

                        qty_reserved = line.reserved_uom_qty or line.product_uom_qty

                        qty = min(qty_reserved, remaining)

                        line.qty_done = qty
                        remaining -= qty

        return res