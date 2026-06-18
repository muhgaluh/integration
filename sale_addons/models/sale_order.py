from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    availability_status = fields.Selection([
        ('to_approve', 'To Be Approved'),
        ('quotation', 'Quotation'),
        ('quotation_sent', 'Quotation Sent'),
        ('sales_order', 'Sales Order'),
        ('done', 'Done'),
    ], string='Status', compute='_compute_availability_status')

    @api.depends('state', 'picking_ids.state')
    def _compute_availability_status(self):
        for order in self:

            # Draft quotation
            if order.state == 'draft':
                order.availability_status = 'quotation'

            # Quotation sent
            elif order.state == 'sent':
                order.availability_status = 'quotation_sent'

            # Menunggu approval
            elif order.state == 'to approve':
                order.availability_status = 'to_approve'

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

    # availability_status = fields.Selection([
    #     ('available', 'Available'),
    #     ('partial_available', 'Partial Available'),
    #     ('partial_reserved', 'Partial Reserved'),
    #     ('reserved', 'Reserved'),
    #     ('done', 'Done'),
    #     ('unavailable', 'Out of Stock'),
    # ], string='Availability Status',
    #    compute='_compute_availability_status')


    # @api.depends('order_line.stock_status')
    # def _compute_availability_status(self):

    #     for order in self:

    #         statuses = order.order_line.mapped('stock_status')

    #         if not statuses:
    #             order.availability_status = False

    #         # Prioritas tertinggi
    #         elif 'unavailable' in statuses:
    #             order.availability_status = 'unavailable'

    #         elif 'partial_reserved' in statuses:
    #             order.availability_status = 'partial_reserved'

    #         elif 'partial_available' in statuses:
    #             order.availability_status = 'partial_available'

    #         # Semua line sudah selesai delivery
    #         elif statuses and all(
    #             status == 'done'
    #             for status in statuses
    #         ):
    #             order.availability_status = 'done'

    #         # Semua line sudah reserve atau sudah done
    #         elif statuses and all(
    #             status in ('reserved', 'done')
    #             for status in statuses
    #         ):
    #             order.availability_status = 'reserved'

    #         else:
    #             order.availability_status = 'available'
   