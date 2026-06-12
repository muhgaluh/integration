from odoo import models, fields, api, _

class InswDashboard(models.Model):
    _name = 'insw.dashboard'
    _description = 'INSW Dashboard by Activity'

    name = fields.Char(string='Nama Kegiatan')
    kd_kegiatan = fields.Selection([
        ('29', 'Saldo Awal'),
        ('30', 'Pemasukan (BC 2.0 / 2.3)'),
        ('31', 'Pengeluaran (BC 3.0 / 2.7)'),
        ('32', 'Stock Opname'),
        ('33', 'Adjustment'),
        ('40', 'Produksi / WIP')
    ], string='Kode Kegiatan')
    
    color = fields.Integer(string='Color Index', default=1)
    
    # Compute counts per status
    count_draft = fields.Integer(compute='_compute_stats')
    count_ready = fields.Integer(compute='_compute_stats')
    count_sent = fields.Integer(compute='_compute_stats')
    count_error = fields.Integer(compute='_compute_stats')

    def _compute_stats(self):
        for rec in self:
            domain = [('kd_kegiatan', '=', rec.kd_kegiatan)]
            queues = self.env['insw.queue'].search(domain)
            
            rec.count_draft = len(queues.filtered(lambda x: x.state == 'draft'))
            rec.count_ready = len(queues.filtered(lambda x: x.state == 'ready'))
            rec.count_sent = len(queues.filtered(lambda x: x.state == 'sent'))
            rec.count_error = len(queues.filtered(lambda x: x.state == 'error'))

    def _action_open_filtered_queue(self, state):
        return {
            'name': f'Antrian {self.name} - {state.upper()}',
            'type': 'ir.actions.act_window',
            'res_model': 'insw.queue',
            'view_mode': 'tree,form',
            'domain': [('kd_kegiatan', '=', self.kd_kegiatan), ('state', '=', state)],
            'context': {'default_kd_kegiatan': self.kd_kegiatan, 'default_state': state},
        }

    def action_open_draft(self): return self._action_open_filtered_queue('draft')
    def action_open_ready(self): return self._action_open_filtered_queue('ready')
    def action_open_sent(self): return self._action_open_filtered_queue('sent')
    def action_open_error(self): return self._action_open_filtered_queue('error')