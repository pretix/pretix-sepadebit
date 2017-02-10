import json
import logging

from datetime import date

import dateutil
from django.contrib import messages
from django.db import transaction
from django.db.models import Count
from django.http import FileResponse
from django.http import HttpResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import ugettext_lazy as _
from django.views.generic import DetailView
from django.views.generic import ListView
from sepadd import SepaDD

from pretix.base.models import Order, orders
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix_sepadebit.models import SepaExport

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
            cnt=Count('orders')
        ).order_by('-datetime')

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['num_new'] = self.get_unexported().count()
        return ctx

    def get_unexported(self):
        return Order.objects.filter(
            event=self.request.event,
            payment_provider='sepadebit',
            status=Order.STATUS_PAID,
            sepa_exports__isnull=True
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

        valid_orders = []
        for order in self.get_unexported():
            if order.payment_info:
                payment_info = json.loads(order.payment_info)
            else:
                # Should not happen
                # TODO: Notify user
                order.status = Order.STATUS_PENDING
                order.save()
                continue

            payment = {
                "name": payment_info['account'],
                "IBAN": payment_info['iban'],
                "BIC": payment_info['bic'],
                "amount": int(order.total * 100),
                "type": "OOFF",
                "collection_date": max(now().date(), dateutil.parser.parse(payment_info['date']).date()),
                "mandate_id": payment_info['reference'],
                "mandate_date": order.datetime.date(),
                "description": _('Event ticket {event}-{code}').format(
                    event=request.event.slug.upper(),
                    code=order.code
                )
            }
            sepa.add_payment(payment)
            valid_orders.append(order)

        if valid_orders:
            with transaction.atomic():
                exp = SepaExport(event=request.event, xmldata='')
                exp.xmldata = sepa.export().decode('utf-8')
                exp.save()
                exp.orders.add(*valid_orders)
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
    context_object_name = 'exports'

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
