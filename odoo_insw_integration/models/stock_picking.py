from odoo import models, fields, _
from odoo.exceptions import UserError

class StockPicking(models.Model):
    _inherit = 'stock.picking'

    insw_status = fields.Selection([
        ('draft', 'INSW Draft'),
        ('sent', 'INSW Sent'),
        ('error', 'INSW Error')
    ], string='Status INSW', copy=False)
    
    insw_queue_id = fields.Many2one('insw.queue', string='INSW Queue', copy=False)

    insw_queue_count = fields.Integer(string='Jumlah INSW', compute='_compute_insw_queue_count')

    def _compute_insw_queue_count(self):
        for rec in self:
            rec.insw_queue_count = self.env['insw.queue'].search_count([('picking_id', '=', rec.id)])

    def action_view_insw_queue(self):
        """Membuka list/form antrian INSW terkait picking ini"""
        self.ensure_one()
        queues = self.env['insw.queue'].search([('picking_id', '=', self.id)])
        
        result = {
            'name': _('Antrian INSW'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'context': {'default_picking_id': self.id},
        }
        
        # Jika cuma 1, langsung buka Form View
        if len(queues) == 1:
            result['view_mode'] = 'form'
            result['res_id'] = queues.id
        else:
            # Jika banyak (misal ada history error), buka Tree View
            result['view_mode'] = 'tree,form'
            result['domain'] = [('picking_id', '=', self.id)]
            
        return result
    
    def action_create_insw_queue(self):
        """Membuat record antrian INSW dari Picking"""
        self.ensure_one()
        if self.state != 'done':
            raise UserError("Hanya dokumen berstatus 'Done' yang bisa dikirim ke INSW.")
        
        # Tentukan Kode Kegiatan Default
        kd_kegiatan = False
        if self.picking_type_code == 'incoming':
            kd_kegiatan = '30' # Pemasukan
        elif self.picking_type_code == 'outgoing':
            kd_kegiatan = '31' # Pengeluaran
        
        # Buat Header Queue
        queue_vals = {
            'sumber_dokumen': 'picking',
            'picking_id': self.id,
            'kd_kegiatan': kd_kegiatan,
            'nomor_dok_kegiatan': self.name,
            'tanggal_kegiatan': self.date_done,
            'lawan_transaksi': self.partner_id.name,
            'state': 'draft'
        }
        
        queue = self.env['insw.queue'].create(queue_vals)
        
        # Buat Lines
        line_vals = []
        for move in self.move_ids_without_package:
            # Estimasi Nilai Barang (Ambil dari Price Unit atau Cost)
            price = move.purchase_line_id.price_unit if move.purchase_line_id else move.product_id.standard_price
            total_nilai = price * move.quantity_done
            
            line_vals.append((0, 0, {
                'product_id': move.product_id.id,
                'kd_barang': move.product_id.default_code,
                'uraian_barang': move.product_id.name,
                'jumlah': move.quantity_done,
                'satuan_id': move.product_uom.id,
                'nilai_barang': total_nilai
            }))
            
        queue.write({'line_ids': line_vals})
        
        self.insw_status = 'draft'
        self.insw_queue_id = queue.id
        
        # Redirect ke Form View Queue
        return {
            'name': _('INSW Queue'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }