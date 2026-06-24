from odoo import models, fields, api

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    availability_status = fields.Selection([
        ('quotation', 'Quotation'),
        ('quotation_sent', 'Quotation Sent'),
        ('sales_order', 'Sales Order'),
        ('done', 'Done'),
        ('cancelled', 'Cancelled'),
    ], string='Status', compute='_compute_availability_status')

    @api.depends('state', 'picking_ids.state')
    def _compute_availability_status(self):
        for order in self:

             # Cancelled
            if order.state == 'cancel':
                order.availability_status = 'cancelled'

            # Draft quotation
            elif order.state == 'draft':
                order.availability_status = 'quotation'

            # Quotation sent
            elif order.state == 'sent':
                order.availability_status = 'quotation_sent'

            # Sales Order yang delivery-nya sudah selesai semua
            elif order.state == 'sale':
                deliveries = order.picking_ids.filtered(
                    lambda p: p.picking_type_code == 'outgoing'
                )

                if deliveries and all(
                    picking.state == 'done'
                    for picking in deliveries
                ):
                    order.availability_status = 'done'
                else:
                    order.availability_status = 'sales_order'

            # Order selesai / locked
            elif order.state == 'done':
                order.availability_status = 'done'

            else:
                order.availability_status = False
