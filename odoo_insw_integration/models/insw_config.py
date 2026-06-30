from odoo import models, fields, api

class InswConfig(models.Model):
    _name = 'insw.config'
    _description = 'Konfigurasi API INSW'
    _rec_name = 'environment'

    api_version = fields.Selection([
    ('1.5', 'Version 1.5'),
    ('1.6', 'Version 1.6'),
    ], string='API Version', default='1.6', required=True)

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

    nib_perusahaan = fields.Char(
        string='NIB',
        help="NIB Perusahaan yang dikirim ke API INSW (Versi 1.5)"
    )

    @api.model
    def get_config(self):
        return self.search([], limit=1)

    @api.onchange('api_version', 'environment')
    def _onchange_api_version_environment(self):
        """Mengisi otomatis Base URL sesuai versi API dan environment."""

        # API Version 1.5
        if self.api_version == '1.5':
            self.url_api = "https://api.insw.go.id"
            return

        # API Version 1.6
        if self.environment == 'dev':
            self.url_api = "https://api-dev.insw.go.id"
        else:
            self.url_api = "https://api.insw.go.id"