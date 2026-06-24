# from odoo import models, fields, api, _
# from odoo.exceptions import UserError

# class MrpProduction(models.Model):
#     _inherit = 'mrp.production'

#     insw_status = fields.Selection([
#         ('draft', 'INSW Draft'),
#         ('sent', 'INSW Sent'),
#         ('error', 'INSW Error')
#     ], string='Status INSW', copy=False)

#     insw_queue_id = fields.Many2one('insw.queue', string='INSW Queue Terakhir', copy=False)
    
#     # Compute field untuk Smart Button
#     insw_queue_count = fields.Integer(string='Jumlah INSW', compute='_compute_insw_queue_count')

#     def _compute_insw_queue_count(self):
#         for rec in self:
#             rec.insw_queue_count = self.env['insw.queue'].search_count([('production_id', '=', rec.id)])

#     def action_view_insw_queue(self):
#         """Membuka list/form antrian INSW terkait MO ini"""
#         self.ensure_one()
#         queues = self.env['insw.queue'].search([('production_id', '=', self.id)])
        
#         result = {
#             'name': _('Antrian INSW (WIP)'),
#             'type': 'ir.actions.act_window',
#             'res_model': 'insw.queue',
#             'context': {'default_production_id': self.id, 'default_sumber_dokumen': 'production'},
#         }
        
#         if len(queues) == 1:
#             result['view_mode'] = 'form'
#             result['res_id'] = queues.id
#         else:
#             result['view_mode'] = 'tree,form'
#             result['domain'] = [('production_id', '=', self.id)]
            
#         return result

#     def action_create_insw_queue(self):
#         """Membuat record antrian INSW dari Manufacturing Order"""
#         self.ensure_one()
#         if self.state != 'done':
#             raise UserError("Hanya MO berstatus 'Done' yang bisa dilaporkan ke INSW.")
        
#         # 1. Siapkan Header
#         # Kode Kegiatan '40' untuk Produksi/WIP (Sesuai kesepakatan internal mapping)
#         queue_vals = {
#             'sumber_dokumen': 'production',
#             'production_id': self.id,
#             'kd_kegiatan': '40', 
#             'nomor_dok_kegiatan': self.name,
#             'tanggal_kegiatan': self.date_finished or fields.Date.today(),
#             'lawan_transaksi': self.company_id.name, # Untuk WIP, entitasnya diri sendiri
#             'state': 'draft'
#         }
        
#         queue = self.env['insw.queue'].create(queue_vals)
        
#         # 2. Siapkan Lines (Ambil dari Komponen/Raw Materials)
#         line_vals = []
        
#         # Kita looping stock.move bahan baku yang statusnya Done
#         for move in self.move_raw_ids.filtered(lambda m: m.state == 'done'):
#             # Logic Costing:
#             # Ambil harga unit saat barang keluar (price_unit di stock move biasanya menyimpan cost saat itu)
#             # Jika menggunakan Standard Price, ini akan ambil standard price.
#             # Jika FIFO/AVCO, ini ambil cost layer.
#             price = move.price_unit
#             total_nilai = price * move.quantity_done
            
#             # Skip jika qty 0 (kadang ada komponen batal pakai)
#             if move.quantity_done <= 0:
#                 continue

#             line_vals.append((0, 0, {
#                 'product_id': move.product_id.id,
#                 'kd_barang': move.product_id.default_code,
#                 'uraian_barang': move.product_id.name,
#                 'jumlah': move.quantity_done,
#                 'satuan_id': move.product_uom.id,
#                 'nilai_barang': total_nilai
#             }))
            
#         if not line_vals:
#             raise UserError("Tidak ada komponen bahan baku yang dikonsumsi (Qty Done = 0).")

#         queue.write({'line_ids': line_vals})
        
#         # 3. Update Status di MO
#         self.insw_status = 'draft'
#         self.insw_queue_id = queue.id
        
#         # 4. Redirect ke Form View Queue
#         return {
#             'name': _('INSW Queue WIP'),
#             'type': 'ir.actions.act_window',
#             'res_model': 'insw.queue',
#             'view_mode': 'form',
#             'res_id': queue.id,
#             'target': 'current',
#         }