from odoo import models, fields, api

class InswConfig(models.Model):
    _name = 'insw.config'
    _description = 'Konfigurasi API INSW'
    _rec_name = 'environment'

    environment = fields.Selection([
        ('dev', 'Development / Dummy'),
        ('prod', 'Production')
    ], string='Environment', default='dev', required=True)

    is_mockup = fields.Boolean(string="Mode Mockup (Demo)", 
        help="Jika dicentang, sistem tidak akan mengirim data ke server INSW, tapi langsung memberikan respon SUKSES palsu.")

    url_api = fields.Char(string='Base URL API', required=True, 
        default='https://api-dev.insw.go.id', help="Endpoint API INSW")
    
    api_key = fields.Char(string='X-INSW-KEY', required=True, help="API Key Statis dari LNSW")
    unique_key = fields.Char(string='X-UNIQUE-KEY', help="Token Dinamis dari getUniqueKey")
    
    npwp_perusahaan = fields.Char(string='NPWP Perusahaan', size=16, 
        help="Format 15/16 digit tanpa tanda baca")

    @api.model
    def get_config(self):
        return self.search([], limit=1)