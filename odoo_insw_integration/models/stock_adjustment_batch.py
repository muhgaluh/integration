from odoo import models, fields, api, _
from odoo.exceptions import UserError

class StockAdjustmentBatch(models.Model):
    _inherit = 'stock.adjustment.batch'

    insw_status = fields.Selection([
        ('draft', 'INSW Draft'),
        ('sent', 'INSW Sent'),
        ('error', 'INSW Error')
    ], string='Status INSW', copy=False)

    insw_report_type = fields.Selection([
        ('stock_opname', 'Stock Opname'),
        ('adjustment', 'Adjustment'),
    ], string='Jenis Laporan',
       default='stock_opname',
       tracking=True)

    insw_queue_id = fields.Many2one('insw.queue', string='INSW Queue Terakhir', copy=False)
    # insw_stock_opname_queue_id = fields.Many2one('insw.queue', string='INSW Stock Opname', copy=False)
    # insw_adjustment_queue_id = fields.Many2one('insw.queue', string='INSW Adjustment', copy=False)
    
    insw_queue_stock_opname_count = fields.Integer(string='Jumlah INSW Stock Opname', compute='_compute_insw_counts')
    insw_queue_adjustment_count = fields.Integer(string='Jumlah INSW Adjustment', compute='_compute_insw_counts')

    def _compute_insw_counts(self):
        for rec in self:

            rec.insw_queue_stock_opname_count = self.env[
                'insw.queue'
            ].search_count([
                ('opname_id', '=', rec.id)
            ])

            rec.insw_queue_adjustment_count = self.env[
                'insw.queue'
            ].search_count([
                ('adjustment_id', '=', rec.id)
            ])

    # View Stock Opname
    def action_view_insw_stock_opname_queue(self):
        self.ensure_one()
        queues = self.env['insw.queue'].search([('opname_id', '=', self.id)])
        result = {
            'name': _('Antrian INSW (Stock Opname)'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'context': {'default_opname_id': self.id, 'default_sumber_dokumen': 'opname'},
        }
        if len(queues) == 1:
            result['view_mode'] = 'form'
            result['res_id'] = queues.id
        else:
            result['view_mode'] = 'tree,form'
            result['domain'] = [('opname_id', '=', self.id)]
        return result
    
    # View Adjustment
    def action_view_insw_adjustment_queue(self):
        self.ensure_one()
        queues = self.env['insw.queue'].search([('adjustment_id', '=', self.id)])
        result = {
            'name': _('Antrian INSW (Adjustment)'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'context': {'default_adjustment_id': self.id, 'default_sumber_dokumen': 'adjustment'},
        }
        if len(queues) == 1:
            result['view_mode'] = 'form'
            result['res_id'] = queues.id
        else:
            result['view_mode'] = 'tree,form'
            result['domain'] = [('adjustment_id', '=', self.id)]
        return result

    # Create INSW Stock Opname (Lapor Stock Opname (INSW))
    def action_create_insw_stock_opname_queue(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError("Hanya dokumen berstatus 'Done' yang bisa dilaporkan ke INSW.")

        # 1. Siapkan Header
        queue_vals = {
            'sumber_dokumen': 'opname',
            'opname_id': self.id,
            'kd_kegiatan': '32', # Kode 32 untuk Stock Opname
            'nomor_dok_kegiatan': self.name,
            'tanggal_kegiatan': self.date or fields.Datetime.now(),
            'lawan_transaksi': self.env.company.name,
            'keterangan': self.reason or 'Stock Opname',
            'state': 'draft'
        }
        
        queue = self.env['insw.queue'].create(queue_vals)
        line_vals = []
        
        # 2. Filter Baris (Hanya yang difference != 0)
        # Sesuai data structure, kita ambil difference 
        lines_to_report = self.line_ids.filtered(lambda l: l.difference != 0)
        
        if not lines_to_report:
            raise UserError("Tidak ada selisih stok (Difference = 0). Tidak perlu dilaporkan ke INSW.")

        for line in lines_to_report:
            # Nilai Harga Total (Menggunakan absolute difference dikali harga standar/modal)
            cost = line.product_id.standard_price
            total_nilai = cost * abs(line.difference)
            
            line_vals.append((0, 0, {
                'product_id': line.product_id.id,
                'kd_barang': line.product_id.default_code,
                'uraian_barang': line.product_id.name,
                'jumlah': line.difference, # Bisa minus (-20) atau plus (+10) sesuai payload spek
                'satuan_id': line.product_id.uom_id.id,
                'nilai_barang': total_nilai
            }))
            
        queue.write({'line_ids': line_vals})
        
        self.insw_status = 'draft'
        self.insw_queue_id = queue.id
        
        return {
            'name': _('INSW Queue Stock Opname'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }

    # Create Adjustment (Lapor Adjustment (INSW))
    def action_create_insw_adjustment_queue(self):
        self.ensure_one()
        if self.state != 'done':
            raise UserError("Hanya dokumen berstatus 'Done' yang bisa dilaporkan ke INSW.")
        

        # 1. Siapkan Header
        queue_vals = {
            'sumber_dokumen': 'adjustment',
            'adjustment_id': self.id,
            'kd_kegiatan': '33', # Kode 33 untuk Adjustment
            'nomor_dok_kegiatan': self.name,
            'tanggal_kegiatan': self.date or fields.Datetime.now(),
            'lawan_transaksi': self.env.company.name,
            'keterangan': self.reason or 'Adjustment Stok',
            'state': 'draft'
        }
        
        queue = self.env['insw.queue'].create(queue_vals)
        line_vals = []
        
        # 2. Filter Baris (Hanya yang difference != 0)
        # Sesuai data structure, kita ambil difference 
        lines_to_report = self.line_ids.filtered(lambda l: l.difference != 0)
        
        if not lines_to_report:
            raise UserError("Tidak ada selisih stok (Difference = 0). Tidak perlu dilaporkan ke INSW.")

        for line in lines_to_report:
            # Nilai Harga Total (Menggunakan absolute difference dikali harga standar/modal)
            cost = line.product_id.standard_price
            total_nilai = cost * abs(line.difference)
            
            line_vals.append((0, 0, {
                'product_id': line.product_id.id,
                'kd_barang': line.product_id.default_code,
                'uraian_barang': line.product_id.name,
                'jumlah': line.difference, # Bisa minus (-20) atau plus (+10) sesuai payload spek
                'satuan_id': line.product_id.uom_id.id,
                'nilai_barang': total_nilai
            }))
            
        queue.write({'line_ids': line_vals})
        
        self.insw_status = 'draft'
        self.insw_queue_id = queue.id
        
        return {
            'name': _('INSW Queue Adjustment'),
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'view_mode': 'form',
            'res_id': queue.id,
            'target': 'current',
        }