import json
import logging

import dateutil
from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from django.views.generic import DetailView, ListView
from pretix.base.models import Order, OrderPayment
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix_sepadebit.models import SepaExport, SepaExportOrder
from sepaxml import SepaDD

logger = logging.getLogger(__name__)


class ExportListView(EventPermissionRequiredMixin, ListView):
    template_name = 'pretix_sepadebit/export.html'
    permission = 'can_change_orders'
    model = SepaExport
    context_object_name = 'exports'

    def get_queryset(self):
        return SepaExport.objects.filter(
            event=self.request.event
        ).annotate(
            cnt=Count('sepaexportorder'),
            sum=Sum('sepaexportorder__amount'),
        ).order_by('-datetime')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['num_new'] = self.get_unexported().count()
        return ctx

    def get_unexported(self):
        return OrderPayment.objects.filter(
            order__event=self.request.event,
            provider='sepadebit',
            state=OrderPayment.PAYMENT_STATE_CONFIRMED,
            order__testmode=self.request.event.testmode,
            sepaexportorder__isnull=True
        )

    def post(self, request, *args, **kwargs):
        config = {
            "name": request.event.settings.payment_sepadebit_creditor_name,
            "IBAN": request.event.settings.payment_sepadebit_creditor_iban,
            "BIC": request.event.settings.payment_sepadebit_creditor_bic,
            "batch": True,
            "creditor_id": request.event.settings.payment_sepadebit_creditor_id,
            "currency": request.event.currency
        }
        sepa = SepaDD(config, schema='pain.008.003.02')

        valid_payments = []
        for payment in self.get_unexported():
            if not payment.info_data:
                # Should not happen
                # TODO: Notify user
                payment.state = OrderPayment.PAYMENT_STATE_FAILED
                payment.save()
                payment.order.status = Order.STATUS_PENDING
                payment.order.save()
                continue

            payment_dict = {
                "name": payment.info_data['account'],
                "IBAN": payment.info_data['iban'],
                "BIC": payment.info_data['bic'],
                "amount": int(payment.amount * 100),
                "type": "OOFF",
                "collection_date": max(now().date(), dateutil.parser.parse(payment.info_data['date']).date()),
                "mandate_id": payment.info_data['reference'],
                "mandate_date": (payment.order.datetime if payment.migrated else payment.created).date(),
                "description": _('Event ticket {event}-{code}').format(
                    event=request.event.slug.upper(),
                    code=payment.order.code
                )
            }
            sepa.add_payment(payment_dict)
            valid_payments.append(payment)

        if valid_payments:
            with transaction.atomic():
                exp = SepaExport(event=request.event, xmldata='')
                exp.xmldata = sepa.export().decode('utf-8')
                exp.testmode = request.event.testmode
                exp.save()
                SepaExportOrder.objects.bulk_create([
                    SepaExportOrder(order=p.order, payment=p, export=exp, amount=p.amount) for p in valid_payments
                ])
            messages.success(request, _('A new export file has been created.'))
        else:
            messages.warning(request, _('No valid orders have been found.'))
        return redirect(reverse('plugins:pretix_sepadebit:export', kwargs={
            'event': request.event.slug,
            'organizer': request.event.organizer.slug,
        }))


class DownloadView(EventPermissionRequiredMixin, DetailView):
    permission = 'can_change_orders'
    model = SepaExport

    def get_object(self, *args, **kwargs):
        return SepaExport.objects.get(
            event=self.request.event,
            pk=self.kwargs.get('id')
        )

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        resp = HttpResponse(self.object.xmldata, content_type='application/xml')
        resp['Content-Disposition'] = 'attachment; filename="{}-{}.xml"'.format(
            self.request.event.slug.upper(),
            self.object.datetime.strftime('%Y-%m-%d-%H-%M-%S'),
        )
        return resp


class OrdersView(EventPermissionRequiredMixin, DetailView):
    permission = 'can_change_orders'
    model = SepaExport
    context_object_name = 'export'
    template_name = 'pretix_sepadebit/orders.html'

    def get_object(self, *args, **kwargs):
        return SepaExport.objects.get(
            event=self.request.event,
            pk=self.kwargs.get('id')
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['seorders'] = self.object.sepaexportorder_set.select_related('order', 'payment').prefetch_related(
            'order__invoices')
        ctx['total'] = self.object.sepaexportorder_set.aggregate(sum=Sum('amount'))['sum']
        return ctx
