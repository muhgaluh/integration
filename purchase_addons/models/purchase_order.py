# models/purchase_order.py

from odoo import models, fields, api


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    purchase_status = fields.Selection([
        ('rfq', 'RFQ'), # Draft
        ('rfq_sent', 'RFQ Sent'), # Send By Email
        ('to_approve', 'To Approve'), # Approve
        ('purchase', 'Purchase Order'), # Purchase Order
        ('partial_received', 'Partial Received'), # Kondisi Kalau Ada Backorder
        ('received', 'Received'), # Validate Receipts kondisi semua barang PO terpenuhi
        ('done', 'Done'), # Harus Di Lock
        ('cancelled', 'Cancelled'), # Cancel
    ], compute='_compute_purchase_status')

    @api.depends('state','order_line.qty_received','order_line.product_qty')
    def _compute_purchase_status(self):

        for order in self:

            # RFQ
            if order.state == 'draft':
                order.purchase_status = 'rfq'

            elif order.state == 'sent':
                order.purchase_status = 'rfq_sent'

            elif order.state == 'to approve':
                order.purchase_status = 'to_approve'

            elif order.state == 'cancel':
                order.purchase_status = 'cancelled'

            elif order.state == 'done':
                order.purchase_status = 'done'

            elif order.state == 'purchase':

                lines = order.order_line.filtered(
                    lambda l: not l.display_type
                )

                if not lines:
                    order.purchase_status = 'purchase'
                    continue

                total_qty = sum(lines.mapped('product_qty'))
                received_qty = sum(lines.mapped('qty_received'))

                if received_qty <= 0:
                    order.purchase_status = 'purchase'

                elif received_qty < total_qty:
                    order.purchase_status = 'partial_received'

                else:
                    order.purchase_status = 'received'