from odoo import models, fields

class ProductCategory(models.Model):
    _inherit = 'product.category'

    # Referensi: III.2. [cite_start]Kategori Barang [cite: 907]
    insw_commodity_code = fields.Selection([
        ('1', '1 - Bahan Baku'),
        ('2', '2 - Bahan Penolong'),
        ('3', '3 - Bahan Habis Pakai'),
        ('4', '4 - Barang Dagangan'),
        ('5', '5 - Mesin dan Peralatan'),
        ('6', '6 - Barang dalam proses'),
        ('7', '7 - Barang Jadi'),
        ('8', '8 - Barang Reject & Scrap'),
    ], string='Kategori Barang INSW', help="Mapping Kategori untuk INSW")

class UoM(models.Model):
    _inherit = 'uom.uom'

    # Referensi: III.5. [cite_start]Data Satuan [cite: 918]
    insw_uom_code = fields.Char(string='Kode Satuan INSW', size=3, 
        help="Contoh: KGM, PCE, LTR, MTR. Lihat tabel referensi PDF.")