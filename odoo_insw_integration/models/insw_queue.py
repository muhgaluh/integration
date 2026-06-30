import requests
import json
import random
from datetime import datetime
from odoo import models, fields, api, _
from odoo.exceptions import UserError

class InswQueue(models.Model):
    _name = 'insw.queue'
    _description = 'Antrian Transaksi INSW'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(string='Referensi', required=True, copy=False, readonly=True, default='New')
    
    # --- Sumber Dokumen (Updated) ---
    sumber_dokumen = fields.Selection([
        ('opening', 'Opening Balance'),
        ('picking', 'Logistik (Picking)'),
        ('opname', 'Stock Opname'),
        ('adjustment', 'Adjustment'),
        # ('production', 'Produksi (WIP)'),
    ], string='Sumber Data', readonly=True)

    opening_balance_id = fields.Many2one('stock.opening.batch', string='Dokumen Saldo Awal', readonly=True)
    picking_id = fields.Many2one('stock.picking', string='Dokumen Logistik', readonly=True)
    opname_id  = fields.Many2one('stock.adjustment.batch', string='Dokumen Stock Opname', readonly=True)
    production_id = fields.Many2one('mrp.production', string='Dokumen Produksi', readonly=True)
    adjustment_id = fields.Many2one('stock.adjustment.batch', string='Dokumen Adjustment', readonly=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('ready', 'Ready to Send'),
        ('sent', 'Sent (Success)'),
        ('error', 'Error')
    ], string='Status', default='draft', tracking=True)

    # --- Header Data ---
    kd_kegiatan = fields.Selection([
        ('29', '29 - Saldo Awal'),
        ('30', '30 - Pemasukan'),
        ('31', '31 - Pengeluaran'),
        ('32', '32 - Stock Opname'),
        ('33', '33 - Adjustment'),
        # ('40', '40 - Produksi / WIP')  # Kode Custom untuk Internal Mapping
    ], string='Jenis Kegiatan', required=True)

    nomor_dok_kegiatan = fields.Char(string='No. Dokumen Kegiatan', required=True, help="Nomor Bukti Penerimaan/Pengeluaran Barang")
    # tanggal_kegiatan = fields.Date(string='Tgl. Kegiatan', required=True, default=fields.Date.context_today)
    
    tanggal_kegiatan = fields.Datetime(string='Tgl. Kegiatan', required=True, default=fields.Datetime.now)
    tanggal_declare = fields.Datetime(string='Tanggal Declare INSW', readonly=True, copy=False, tracking=True)
    
    lawan_transaksi = fields.Char(string='Lawan Transaksi (Entitas)', help="Supplier atau Customer")
    
    # Field tambahan khusus Adjustment
    keterangan = fields.Char(string='Keterangan / Alasan', help="Keterangan dokumen untuk Adjustment")

    # --- Field Agregat Nilai & Currency (Dasbor & Produksi) ---
    currency_id = fields.Many2one('res.currency', string='Currency', default=lambda self: self.env.company.currency_id.id)
    total_nilai_transaksi = fields.Monetary(string='Total Nilai', compute='_compute_total_biaya', store=True)
    total_biaya_produksi = fields.Float(string='Total Biaya Bahan Baku', compute='_compute_total_biaya', store=True)

    # --- Dokumen Pabean (Input Manual User) ---
    kode_dokumen_bc = fields.Selection([
        ('0407020', 'BC 2.0 - PIB'),
        ('0407023', 'BC 2.3 - Gudang Berikat'),
        ('0407030', 'BC 3.0 - PEB'),
        ('0407008', 'Free Movement'),
        ('0407611', 'PPKEK Pemasukan TLDDP'),
        ('0407612', 'PPKEK Pengeluaran TLDDP'),
        ('0407000', 'Dokumen Pabean Lainnya'),
    ], string='Jenis Dokumen')
    
    nomor_aju = fields.Char(string='Nomor Aju / Daftar', help="Nomor Pengajuan")
    nomor_dokumen_bc = fields.Char(string='Nomor Dokumen', help="Nomor Dokumen")
    tanggal_dokumen_bc = fields.Date(string='Tanggal Dokumen')

    # --- Lines ---
    line_ids = fields.One2many('insw.queue.line', 'queue_id', string='Detail Barang')

    # --- Log Response ---
    insw_id_transaksi = fields.Char(string='INSW ID Transaksi', readonly=True, copy=False)
    api_endpoint = fields.Char(string='API Endpoint', readonly=True, copy=False)
    json_payload = fields.Text(string='JSON Terkirim', readonly=True)
    json_response = fields.Text(string='JSON Balasan', readonly=True)
    error_message = fields.Text(string='Pesan Error', readonly=True)

    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('insw.queue') or 'New'
        return super(InswQueue, self).create(vals)

    @api.depends('line_ids.nilai_barang')
    def _compute_total_biaya(self):
        """Menghitung total cost material yang dikonsumsi / nilai barang"""
        for rec in self:
            total = sum(line.nilai_barang for line in rec.line_ids)
            rec.total_biaya_produksi = total
            rec.total_nilai_transaksi = total

    def action_validate(self):
        """Kunci data agar tidak bisa diedit sebelum kirim"""
        for rec in self:
            if not rec.line_ids:
                raise UserError("Detail barang tidak boleh kosong!")
            
            # Validasi master data
            for line in rec.line_ids:
                if not line.kd_kategori_barang:
                    raise UserError(f"Produk {line.product_id.name} belum memiliki Kategori INSW!")
                if not line.kd_satuan:
                    raise UserError(f"Satuan {line.satuan_id.name} belum memiliki Kode Satuan INSW!")
            
            rec.state = 'ready'

    def action_set_draft(self):
        """Revisi data jika error"""
        self.state = 'draft'

    def action_send_insw(self):
        """Fungsi utama pengiriman data ke API"""
        config = self.env['insw.config'].search([], limit=1)
        if not config:
            raise UserError("Konfigurasi INSW belum disetting!")

        headers = {
            'Content-Type': 'application/json',
            'x-insw-key': config.api_key,
            'x-unique-key': config.unique_key or ''
        }

        # Susun Payload 
        nama_entitas = self.lawan_transaksi
        if self.sumber_dokumen in ['production', 'adjustment'] and not nama_entitas:
            nama_entitas = self.env.company.name

        # Waktu Sesuai Lokal
        local_dt = False

        if self.tanggal_kegiatan:
            local_dt = fields.Datetime.context_timestamp(
                self.with_context(tz='Asia/Jakarta'),
                self.tanggal_kegiatan
            )
        
        # PILIH PAYLOAD BERDASARKAN KEGIATAN
        if self.kd_kegiatan == '29':
            # payload_data = self.payload_saldo_awal(local_dt, local_declare_dt)
            payload_data = self.payload_saldo_awal(local_dt)

        elif self.kd_kegiatan == '30':
            payload_data = self.payload_pemasukan(local_dt, nama_entitas)

        elif self.kd_kegiatan == '31':
            payload_data = self.payload_pengeluaran(local_dt, nama_entitas)

        elif self.kd_kegiatan == '32':
            payload_data = self.payload_stock_opname(local_dt, nama_entitas)

        elif self.kd_kegiatan == '33':
            payload_data = self.payload_adjustment(local_dt, nama_entitas)

        # elif self.kd_kegiatan == '40':
        #     raise UserError(
        #         "Kegiatan Produksi (40) tidak dikirim ke API INSW."
        #     )

        else:
            raise UserError(
                f"Jenis kegiatan {self.kd_kegiatan} belum didukung"
            )

        final_payload = {"data": payload_data if self.kd_kegiatan == '29' else [payload_data]}
        self.json_payload = json.dumps(final_payload, indent=4)

        # ==========================================
        #       JALUR KHUSUS MOCKUP / DEMO
        # ==========================================
        if config.is_mockup:
            # Simulasi ID Transaksi Unik
            mock_id = f"TRX-DEMO-{fields.Date.today()}-{random.randint(1000,9999)}"
            
            # Simulasi JSON Response dari INSW (Format Code 01)
            mock_response = {
                "code": "01",
                "message": "SUKSES (MOCKUP MODE)",
                "data": {
                    "resultDataTransaksi": [{
                        "idTransaksi": mock_id,
                        # "nomorAju": self.nomor_aju or "AJU-DUMMY",
                        "nomorDokumen": self.nomor_dokumen_bc or "Dokumen-DUMMY",
                        "waktuRekam": fields.Datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    }]
                }
            }
            
            # Simpan Log Palsu
            self.json_response = json.dumps(mock_response, indent=4)
            self.insw_id_transaksi = mock_id
            
            # Ubah Status jadi Sent
            self.state = 'sent'
            self.error_message = False
            
            # Update Dokumen Asal (Picking / Production / Adjustment)
            if self.opening_balance_id:
                self.opening_balance_id.insw_status = 'sent'
            if self.picking_id:
                self.picking_id.insw_status = 'sent'
            if self.opname_id:
                self.opname_id.insw_status = 'sent'
            if self.adjustment_id:
                self.adjustment_id.insw_status = 'sent'
            # if self.production_id:
            #     self.production_id.insw_status = 'sent'   

            # STOP DI SINI (Jangan kirim request asli)
            return 

        # ==========================================
        #          JALUR ASLI (REAL API)
        # ==========================================
        # endpoint = f"{config.url_api}/api/inventory/transaksi" 
        endpoint = self._get_endpoint(config) 

        # Simpan endpoint ke log
        self.api_endpoint = endpoint

        try:
            response = requests.post(endpoint, headers=headers, data=json.dumps(final_payload))
            self.json_response = response.text
            
            res_json = response.json()
            
            if res_json.get('code') == '01':
                data_respon = res_json.get('data', {})
                trx_list = data_respon.get('resultDataTransaksi', [])
                if trx_list:
                    self.insw_id_transaksi = trx_list[0].get('idTransaksi')
                
                self.state = 'sent'
                self.error_message = False
                
                # Update Dokumen Asal (Picking OR Production OR Adjustment)
                if self.opening_balance_id:
                    self.opening_balance_id.insw_status = 'sent'
                if self.picking_id:
                    self.picking_id.insw_status = 'sent'
                # if self.production_id:
                #     self.production_id.insw_status = 'sent'
                if self.opname_id:
                    self.opname_id.insw_status = 'sent'
                if self.adjustment_id:
                    self.adjustment_id.insw_status = 'sent'
            else:
                self.state = 'error'
                self.error_message = f"INSW Error: {res_json.get('message')} - {res_json.get('data')}"
                if self.opening_balance_id:
                    self.opening_balance_id.insw_status = 'error'
                if self.picking_id:
                    self.picking_id.insw_status = 'error'
                if self.opname_id:
                    self.opname_id.insw_status = 'error'
                if self.adjustment_id:
                    self.adjustment_id.insw_status = 'error'
                # if self.production_id:
                #     self.production_id.insw_status = 'error'
        except Exception as e:
            self.state = 'error'
            self.error_message = f"Connection Error: {str(e)}"

    # Payload Saldo Awal (29)
    def payload_saldo_awal(self, local_dt):
        config = self.env['insw.config'].get_config()

        payload = {
            "no_kegiatan": self.nomor_dok_kegiatan,
            "tgl_kegiatan": local_dt.strftime('%d-%m-%Y %H:%M:%S') if local_dt else "",
        }

        if config.api_version == '1.5':
            payload.update({
                "npwp": config.npwp_perusahaan or "",
                "nib": config.nib_perusahaan or "",
            })

        payload["barangSaldo"] = []

        for line in self.line_ids:
            item = {
                "kd_kategori_barang": line.kd_kategori_barang,
                "kd_barang": line.kd_barang or "-",
                "uraian_barang": line.uraian_barang or "-",
                "jumlah": line.jumlah,
                "satuan": line.kd_satuan,
                "nilai": line.nilai_barang,
                "tanggal_declare": local_dt.strftime('%d-%m-%Y %H:%M:%S') if local_dt else "",
                # "tanggal_declare": (local_declare_dt.strftime('%d-%m-%Y %H:%M:%S') if local_declare_dt else ""),
            }

            payload["barangSaldo"].append(item)

        return payload

    # Payload Pemasukan (30)
    def payload_pemasukan(self, local_dt, nama_entitas):
        config = self.env['insw.config'].get_config()

        payload = {
            "kdKegiatan": "30",
        }

        if config.api_version == '1.5':
            payload.update({
                "npwp": config.npwp_perusahaan or "",
                "nib": config.nib_perusahaan or "",
            })
        
        # Lanjutan Payload
        payload["dokumenKegiatan"] = [{
                "nomorDokKegiatan": self.nomor_dok_kegiatan,
                "tanggalKegiatan": local_dt.strftime('%d-%m-%Y %H:%M:%S') if local_dt else "",
                "namaEntitas": nama_entitas or "-",
                "barangTransaksi": []
            }]

        for line in self.line_ids:
            item = {
                "kdKategoriBarang": line.kd_kategori_barang,
                "kdBarang": line.kd_barang or "-",
                "uraianBarang": line.uraian_barang or "-",
                "jumlah": line.jumlah,
                "kdSatuan": line.kd_satuan,
                "nilai": line.nilai_barang,
                "dokumen": []
            }

            if self.kode_dokumen_bc:
                item["dokumen"].append({
                    "kodeDokumen": self.kode_dokumen_bc,
                    "nomorDokumen": self.nomor_dokumen_bc or "-",
                    "tanggalDokumen": (
                        self.tanggal_dokumen_bc.strftime('%d-%m-%Y')
                        if self.tanggal_dokumen_bc else ""
                    )
                })

            payload["dokumenKegiatan"][0]["barangTransaksi"].append(item)

        return payload
    
    # Payload Pengeluaran (31)
    def payload_pengeluaran(self, local_dt, nama_entitas):
        config = self.env['insw.config'].get_config()

        payload = {
            "kdKegiatan": "31",
        }

        if config.api_version == '1.5':
            payload.update({
                "npwp": config.npwp_perusahaan or "",
                "nib": config.nib_perusahaan or "",
            })

        payload["dokumenKegiatan"] = [{
                "nomorDokKegiatan": self.nomor_dok_kegiatan,
                "tanggalKegiatan": local_dt.strftime('%d-%m-%Y %H:%M:%S') if local_dt else "",
                "namaEntitas": nama_entitas or "-",
                "barangTransaksi": []
            }]

        for line in self.line_ids:
            item = {
                "kdKategoriBarang": line.kd_kategori_barang,
                "kdBarang": line.kd_barang or "-",
                "uraianBarang": line.uraian_barang or "-",
                "jumlah": line.jumlah,
                "kdSatuan": line.kd_satuan,
                "nilai": line.nilai_barang,
                "dokumen": []
            }

            if self.kode_dokumen_bc:
                item["dokumen"].append({
                    "kodeDokumen": self.kode_dokumen_bc,
                    "nomorDokumen": self.nomor_dokumen_bc or "-",
                    "tanggalDokumen": (
                        self.tanggal_dokumen_bc.strftime('%d-%m-%Y')
                        if self.tanggal_dokumen_bc else ""
                    )
                })

            payload["dokumenKegiatan"][0]["barangTransaksi"].append(item)

        return payload

    # Payload Stock Opname (32)
    def payload_stock_opname(self, local_dt, nama_entitas):
        config = self.env['insw.config'].get_config()

        payload = {
            "kdKegiatan": "32",
        }

        if config.api_version == '1.5':
            payload.update({
                "npwp": config.npwp_perusahaan or "",
                "nib": config.nib_perusahaan or "",
            })
            
        payload["dokumenKegiatan"] = [{
                "nomorDokKegiatan": self.nomor_dok_kegiatan,
                "tanggalKegiatan": local_dt.strftime('%d-%m-%Y %H:%M:%S'),
                "namaEntitas": nama_entitas or "-",
                "barangTransaksi": []
            }]

        for line in self.line_ids:
            item = {
                "kdKategoriBarang": line.kd_kategori_barang,
                "kdBarang": line.kd_barang or "-",
                "uraianBarang": line.uraian_barang or "-",
                "jumlah": line.jumlah,
                "kdSatuan": line.kd_satuan,
                "nilai": line.nilai_barang,
                "dokumen": []
            }

            if self.kode_dokumen_bc:
                item["dokumen"].append({
                    "kodeDokumen": self.kode_dokumen_bc,
                    "nomorDokumen": self.nomor_dokumen_bc or "-",
                    "tanggalDokumen": (
                        self.tanggal_dokumen_bc.strftime('%d-%m-%Y')
                        if self.tanggal_dokumen_bc else ""
                    )
                })

            payload["dokumenKegiatan"][0]["barangTransaksi"].append(item)

        return payload
    
    # Payload Adjustment (33)
    def payload_adjustment(self, local_dt, nama_entitas):
        config = self.env['insw.config'].get_config()

        payload = {
            "kdKegiatan": "33",
        }

        if config.api_version == '1.5':
            payload.update({
                "npwp": config.npwp_perusahaan or "",
                "nib": config.nib_perusahaan or "",
            })

        payload["dokumenKegiatan"] = [{
                "nomorDokKegiatan": self.nomor_dok_kegiatan,
                "tanggalKegiatan": local_dt.strftime('%d-%m-%Y %H:%M:%S'),
                "keterangan": self.keterangan or "-",
                "namaEntitas": nama_entitas or "-",
                "barangTransaksi": []
            }]

        for line in self.line_ids:
            item = {
                "kdKategoriBarang": line.kd_kategori_barang,
                "kdBarang": line.kd_barang or "-",
                "uraianBarang": line.uraian_barang or "-",
                "jumlah": line.jumlah,
                "kdSatuan": line.kd_satuan,
                "nilai": line.nilai_barang,
                "dokumen": []
            }

            if self.kode_dokumen_bc:
                item["dokumen"].append({
                    "kodeDokumen": self.kode_dokumen_bc,
                    "nomorDokumen": self.nomor_dokumen_bc or "-",
                    "tanggalDokumen": (
                        self.tanggal_dokumen_bc.strftime('%d-%m-%Y')
                        if self.tanggal_dokumen_bc else ""
                    )
                })

            payload["dokumenKegiatan"][0]["barangTransaksi"].append(item)

        return payload


    # # Endpoint
    # def _get_endpoint(self, config):
    #     """
    #     Mengembalikan endpoint sesuai environment dan kd_kegiatan.
    #     """
    #     # ==========================================================
    #     # API VERSION 1.5
    #     # ==========================================================
    #     if config.api_version == '1.5':

    #         # Dummy
    #         if config.environment == 'dev':
    #             if self.kd_kegiatan == '29':
    #                 return "https://api.insw.go.id/api-prod/inventory/tempInsertSaldoAwal"
    #             else:
    #                 return "https://api.insw.go.id/api-prod/inventory/pemasukan/tempInsert"

    #         # Production
    #         else:
    #             if self.kd_kegiatan == '29':
    #                 return "https://api.insw.go.id/api-prod/inventory/insertSaldoAwal"
    #             else:
    #                 return "https://api.insw.go.id/api-prod/inventory/pemasukan/insert"

    #     # ==========================================================
    #     # API VERSION 1.6 (Default)
    #     # ==========================================================
    #     if config.environment == 'dev':

    #         # Pengecualian: Dummy Pengeluaran menggunakan domain production
    #         if self.kd_kegiatan == '31':
    #             return "https://api.insw.go.id/api-prod/inventory/pemasukan/tempInsert"

    #         endpoint_map = {
    #             '29': '/api/inventory/temp/saldoAwal',
    #             '30': '/api/inventory/temp/transaksi',
    #             '32': '/api/inventory/temp/transaksi',
    #             '33': '/api/inventory/temp/transaksi',
    #         }

    #     else:
    #         endpoint_map = {
    #             '29': '/api-prod/inventory/saldoAwal',
    #             '30': '/api-prod/inventory/transaksi',
    #             '31': '/api-prod/inventory/pemasukan/insert',
    #             '32': '/api-prod/inventory/transaksi',
    #             '33': '/api-prod/inventory/transaksi',
    #         }

    #     endpoint_path = endpoint_map.get(self.kd_kegiatan)

    #     if not endpoint_path:
    #         raise UserError(
    #             _("Endpoint untuk kegiatan %s belum tersedia.")
    #             % self.kd_kegiatan
    #         )

    #     return "%s%s" % (
    #         config.url_api.rstrip('/'),
    #         endpoint_path
    #     )

    # Endpoint
    def _get_endpoint(self, config):
        """
        Mengembalikan endpoint sesuai API Version, Environment dan Jenis Kegiatan.
        """

        # ==========================================================
        # API VERSION 1.5
        # ==========================================================
        if config.api_version == '1.5':

            if config.environment == 'dev':
                endpoint_map = {
                    '29': '/api-prod/inventory/tempInsertSaldoAwal',
                    '30': '/api-prod/inventory/pemasukan/tempInsert',
                    '31': '/api-prod/inventory/pemasukan/tempInsert',
                    '32': '/api-prod/inventory/pemasukan/tempInsert',
                    '33': '/api-prod/inventory/pemasukan/tempInsert',
                }
            else:
                endpoint_map = {
                    '29': '/api-prod/inventory/insertSaldoAwal',
                    '30': '/api-prod/inventory/pemasukan/insert',
                    '31': '/api-prod/inventory/pemasukan/insert',
                    '32': '/api-prod/inventory/pemasukan/insert',
                    '33': '/api-prod/inventory/pemasukan/insert',
                }

            endpoint_path = endpoint_map.get(self.kd_kegiatan)

            if not endpoint_path:
                raise UserError(
                    _("Endpoint untuk kegiatan %s belum tersedia.")
                    % self.kd_kegiatan
                )

            return "%s%s" % (
                config.url_api.rstrip('/'),
                endpoint_path
            )

        # ==========================================================
        # API VERSION 1.6
        # ==========================================================
        if config.environment == 'dev':

            # Khusus KD 31 tetap menggunakan domain production
            if self.kd_kegiatan == '31':
                return "https://api.insw.go.id/api-prod/inventory/pemasukan/tempInsert"

            endpoint_map = {
                '29': '/api/inventory/temp/saldoAwal',
                '30': '/api/inventory/temp/transaksi',
                '32': '/api/inventory/temp/transaksi',
                '33': '/api/inventory/temp/transaksi',
            }

        else:
            endpoint_map = {
                '29': '/api-prod/inventory/saldoAwal',
                '30': '/api-prod/inventory/transaksi',
                '31': '/api-prod/inventory/pemasukan/insert',
                '32': '/api-prod/inventory/transaksi',
                '33': '/api-prod/inventory/transaksi',
            }

        endpoint_path = endpoint_map.get(self.kd_kegiatan)

        if not endpoint_path:
            raise UserError(
                _("Endpoint untuk kegiatan %s belum tersedia.")
                % self.kd_kegiatan
            )

        return "%s%s" % (
            config.url_api.rstrip('/'),
            endpoint_path
        )
    
    def action_view_opening_balance(self):
        """Balik ke dokumen Opening Balance Batch"""
        self.ensure_one()
        return {
            'name': _('Dokumen Asal'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.opening.batch',
            'view_mode': 'form',
            'res_id': self.opening_balance_id.id,
            'target': 'current',
        }
    
    def action_view_picking(self):
        """Balik ke dokumen Picking"""
        self.ensure_one()
        return {
            'name': _('Dokumen Asal'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.picking_id.id,
            'target': 'current',
        }

    def action_view_stock_opname(self):
        """Balik ke dokumen Adjustment Batch (Stock Opname)"""
        self.ensure_one()
        return {
            'name': _('Dokumen Stock Opname'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.adjustment.batch',
            'view_mode': 'form',
            'res_id': self.opname_id.id,
            'target': 'current',
        }
    
    def action_view_adjustment(self):
        """Balik ke dokumen Adjustment Batch"""
        self.ensure_one()
        return {
            'name': _('Dokumen Adjustment'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.adjustment.batch',
            'view_mode': 'form',
            'res_id': self.adjustment_id.id,
            'target': 'current',
        }

    def action_view_production(self):
        """Balik ke dokumen Produksi (MO)"""
        self.ensure_one()
        return {
            'name': _('Dokumen Produksi'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'form',
            'res_id': self.production_id.id,
            'target': 'current',
        }


class InswQueueLine(models.Model):
    _name = 'insw.queue.line'
    _description = 'Detail Barang INSW'

    queue_id = fields.Many2one('insw.queue', string='Header', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Product')
    
    kd_barang = fields.Char(string='Kode Barang')
    uraian_barang = fields.Char(string='Uraian Barang')
    
    kd_kategori_barang = fields.Selection(related='product_id.categ_id.insw_commodity_code', 
        string='Kategori INSW', store=True, readonly=False)
    
    jumlah = fields.Float(string='Jumlah')
    
    satuan_id = fields.Many2one('uom.uom', string='Satuan Odoo')
    kd_satuan = fields.Char(related='satuan_id.insw_uom_code', 
        string='Kode Satuan INSW', store=True, readonly=False)
    
    nilai_barang = fields.Float(string='Nilai (Rp)', default=0.0, help="Total Harga Barang (CIF/Harga Perolehan)")