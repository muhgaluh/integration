from odoo import api, fields, models
from odoo.exceptions import UserError

class StockOpeningBatch(models.Model):
    _inherit = 'stock.opening.batch'

    insw_status = fields.Selection([
        ('draft', 'INSW Draft'),
        ('sent', 'INSW Sent'),
        ('error', 'INSW Error')
    ], string='Status INSW', copy=False)

    insw_opening_queue_id = fields.Many2one('insw.queue', string='INSW Opening Queue', copy=False)

    insw_opening_queue_count = fields.Integer(string='Jumlah INSW', compute='_compute_insw_queue_count')

    def _compute_insw_queue_count(self):
        for rec in self:
            rec.insw_opening_queue_count = self.env['insw.queue'].search_count([('opening_balance_id', '=', rec.id)])

    def action_view_insw_opening_queue(self):
        self.ensure_one()

        return {
            'type': 'ir.actions.act_window',
            'name': 'INSW Queue',
            'res_model': 'insw.queue',
            'view_mode': 'form',
            'res_id': self.insw_opening_queue_id.id,
            'target': 'current',
        }

    def action_view_insw_opening_queue(self):
        """Membuka list/form antrian INSW terkait MO ini"""
        self.ensure_one()
        queues = self.env['insw.queue'].search([('opening_balance_id', '=', self.id)])
        
        result = {
            'name': ('Antrian Saldo Awal (Opening Balance)'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'context': {'default_opening_balance_id': self.id, 'default_sumber_dokumen': 'opening'},
        }
        
        if len(queues) == 1:
            result['view_mode'] = 'form'
            result['res_id'] = queues.id
        else:
            result['view_mode'] = 'tree,form'
            result['domain'] = [('opening_balance_id', '=', self.id)]
            
        return result


    def action_create_insw_opening_balance_queue(self):
        """Membuat record antrian INSW dari Opening Balance Batch"""
        self.ensure_one()
        if self.state != 'done':
            raise UserError("Hanya MO berstatus 'Done' yang bisa dilaporkan ke INSW.")
        
        # 1. Siapkan Header
        # Kode Kegiatan '29' untuk Saldo Awal (Opening Balance)
        queue_vals = {
            'sumber_dokumen': 'opening',
            'opening_balance_id': self.id,
            'kd_kegiatan': '29', 
            'nomor_dok_kegiatan': self.name,
            'tanggal_kegiatan': self.date or fields.Datetime.now(),
            'lawan_transaksi': self.env.company.name, # Untuk Company, entitasnya diri sendiri
            'state': 'draft'
        }
        
        queue = self.env['insw.queue'].create(queue_vals)
        
        # 2. Siapkan Lines 
        line_vals = []
        
        for line in self.line_ids:
            total_nilai = line.inventory_value or (
                line.counted_qty * line.unit_cost
            )

            line_vals.append((0, 0, {
                'product_id': line.product_id.id,
                'kd_barang': line.product_id.default_code or '',
                'uraian_barang': line.product_id.name,
                'jumlah': line.counted_qty,
                'satuan_id': line.product_id.uom_id.id,
                'nilai_barang': total_nilai,
            }))
            
        queue.write({'line_ids': line_vals})
        
        # 3. Update Status di Opening Balance
        self.insw_status = 'draft'
        self.insw_opening_queue_id = queue.id
        
        # 4. Redirect ke Form View Queue
        return {
            'name': ('INSW Queue Saldo Awal'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }