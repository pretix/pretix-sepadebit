import datetime
import logging
import os
from collections import defaultdict
from decimal import Decimal

from django.contrib import messages
from django.db import transaction
from django.db.models import Count, Q, Sum, Subquery, OuterRef
from django.db.models.functions import Coalesce
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django.views.generic import DetailView, ListView
from functools import reduce
from operator import or_
from pretix.base.models import Event, Order, OrderPayment, OrderRefund
from pretix.control.permissions import (
    EventPermissionRequiredMixin, OrganizerPermissionRequiredMixin,
)
from pretix.control.views.organizer import OrganizerDetailViewMixin
from sepaxml import SepaDD, validation

from pretix_sepadebit.models import SepaExport, SepaExportOrder

logger = logging.getLogger(__name__)


class ExportListView(ListView):
    template_name = 'pretix_sepadebit/export.html'
    model = SepaExport
    context_object_name = 'exports'

    def get_unexported(self):
        raise NotImplementedError()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data()
        ctx['num_new'] = self.get_unexported().count()
        ctx['basetpl'] = "pretixcontrol/event/base.html"
        if not hasattr(self.request, 'event'):
            ctx['basetpl'] = "pretixcontrol/organizers/base.html"
        return ctx

    def _config_for_event(self, event):
        if event not in self._event_cache:
            self._event_cache[event] = (
                ("name", event.settings.payment_sepadebit_creditor_name),
                ("IBAN", event.settings.payment_sepadebit_creditor_iban),
                ("BIC", event.settings.payment_sepadebit_creditor_bic),
                ("batch", True),
                ("creditor_id", event.settings.payment_sepadebit_creditor_id),
                ("currency", event.currency)
            )
        return self._event_cache[event]

    def _bank_date(self, dt: datetime.date):
        known_holidays = (
            # Based on TARGET2 and Bundesbank list, but omitting variable days like easter because the
            # calculation is cumbersome and it's not that bad if we miss some as banks tend to auto-correct
            (1, 1),
            (5, 1),
            (12, 24),
            (12, 25),
            (12, 26),
            (12, 31),
        )
        while dt.weekday() in (5, 6) or (dt.month, dt.day) in known_holidays:
            dt = dt + datetime.timedelta(days=1)
        return dt

    def post(self, request, *args, **kwargs):
        self._event_cache = {}

        valid_payments = defaultdict(list)
        files = {}
        for payment in self.get_unexported().select_related('order', 'order__event', 'sepadebit_due'):
            if not payment.info_data:
                # Should not happen
                # TODO: Notify user
                payment.state = OrderPayment.PAYMENT_STATE_FAILED
                payment.save()
                payment.order.status = Order.STATUS_PENDING
                payment.order.save()
                continue

            collection_date = self._bank_date(max(now().astimezone(payment.order.event.timezone).date(), payment.sepadebit_due.date))
            remaining_amount = payment.amount - payment.refund_amount
            payment_dict = {
                "name": payment.info_data['account'],
                "IBAN": payment.info_data['iban'],
                "BIC": payment.info_data['bic'],
                "amount": int(remaining_amount * 100),
                "type": "OOFF",
                "collection_date": collection_date,
                "mandate_id": payment.info_data['reference'],
                "mandate_date": (payment.order.datetime if payment.migrated else payment.created).date(),
                "description": _('Event ticket {event}-{code}').format(
                    event=payment.order.event.slug.upper(),
                    code=payment.order.code
                )
            }

            config = self._config_for_event(payment.order.event)
            if request.POST.get("split-by-collection-date") == "on":
                key = (config, collection_date)
            else:
                key = config

            if key not in files:
                files[key] = SepaDD(dict(config), schema='pain.008.001.02')
            file = files[key]
            file.add_payment(payment_dict)
            valid_payments[file].append(payment)

        if valid_payments:
            with transaction.atomic():
                for key, f in list(files.items()):
                    if hasattr(request, 'event'):
                        exp = SepaExport(event=request.event, xmldata='')
                        exp.testmode = request.event.testmode
                    else:
                        exp = SepaExport(organizer=request.organizer, xmldata='')
                        exp.testmode = False
                    exp.xmldata = f.export(validate=False).decode('utf-8')

                    import xmlschema  # xmlschema does some weird monkeypatching in etree, if we import it globally, things fail
                    my_schema = xmlschema.XMLSchema(
                        os.path.join(os.path.dirname(validation.__file__), 'schemas', f.schema + '.xsd')
                    )
                    errs = []
                    for e in my_schema.iter_errors(exp.xmldata):
                        errs.append(str(e))
                    if errs:
                        messages.error(request, _('The generated file did not validate for the following reasons. '
                                                  'Please contact pretix support for more information.\n{}').format(
                            "\n".join(errs)))
                        del files[key]
                    else:
                        exp.currency = f._config['currency']
                        exp.save()
                        SepaExportOrder.objects.bulk_create([
                            SepaExportOrder(order=p.order, payment=p, export=exp, amount=p.amount - p.refund_amount) for p in valid_payments[f]
                        ])
            if len(files) > 1:
                messages.warning(request, _('Multiple new export files have been created. Please make sure to process all of them!'))
            elif len(files) > 0:
                messages.success(request, _('A new export file has been created.'))
        else:
            messages.warning(request, _('No valid orders have been found.'))
        if hasattr(request, 'event'):
            return redirect(reverse('plugins:pretix_sepadebit:export', kwargs={
                'event': request.event.slug,
                'organizer': request.organizer.slug,
            }))
        else:
            return redirect(reverse('plugins:pretix_sepadebit:export', kwargs={
                'organizer': request.organizer.slug,
            }))


class DownloadView(DetailView):
    model = SepaExport

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()

        resp = HttpResponse(self.object.xmldata, content_type='application/xml')
        resp['Content-Disposition'] = 'attachment; filename="{}-{}.xml"'.format(
            self.request.event.slug.upper() if hasattr(self.request, 'event') else self.request.organizer.slug.upper(),
            self.object.datetime.strftime('%Y-%m-%d-%H-%M-%S'),
        )
        return resp


class OrdersView(DetailView):
    model = SepaExport
    context_object_name = 'export'
    template_name = 'pretix_sepadebit/orders.html'

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx['seorders'] = self.object.sepaexportorder_set.select_related('order', 'payment').prefetch_related(
            'order__invoices', 'order__event')
        ctx['total'] = self.object.sepaexportorder_set.aggregate(sum=Sum('amount'))['sum']
        ctx['basetpl'] = "pretixcontrol/event/base.html"
        if not hasattr(self.request, 'event'):
            ctx['basetpl'] = "pretixcontrol/organizers/base.html"
        return ctx


class EventExportListView(EventPermissionRequiredMixin, ExportListView):
    permission = 'can_change_orders'

    def get_queryset(self):
        return SepaExport.objects.filter(
            event=self.request.event
        ).annotate(
            cnt=Count('sepaexportorder'),
            sum=Sum('sepaexportorder__amount'),
        ).order_by('-datetime')

    def get_unexported(self):
        today = now().astimezone(self.request.event.timezone).date()
        latest_export_due_date = today + datetime.timedelta(days=int(self.request.event.settings.payment_sepadebit_prenotification_days or 0))

        return OrderPayment.objects.filter(
            order__event=self.request.event,
            provider='sepadebit',
            state=OrderPayment.PAYMENT_STATE_CONFIRMED,
            order__testmode=self.request.event.testmode,
            sepaexportorder__isnull=True,
            sepadebit_due__date__lte=latest_export_due_date
        ).annotate(
            refund_amount=Coalesce(
                Subquery(OrderRefund.objects.filter(
                    payment=OuterRef('pk'),
                    state=OrderRefund.REFUND_STATE_DONE,
                ).order_by().values('payment').annotate(s=Sum('amount')).values('s')),
                Decimal('0.00'),
            ),
        )


class EventDownloadView(EventPermissionRequiredMixin, DownloadView):
    permission = 'can_change_orders'

    def get_object(self, *args, **kwargs):
        return get_object_or_404(
            SepaExport,
            event=self.request.event,
            pk=self.kwargs.get('id')
        )


class EventOrdersView(EventPermissionRequiredMixin, OrdersView):
    permission = 'can_change_orders'

    def get_object(self, *args, **kwargs):
        return get_object_or_404(
            SepaExport,
            event=self.request.event,
            pk=self.kwargs.get('id')
        )


class OrganizerDownloadView(OrganizerPermissionRequiredMixin, OrganizerDetailViewMixin, DownloadView):
    permission = 'can_change_organizer_settings'

    def get_object(self, *args, **kwargs):
        return get_object_or_404(
            SepaExport,
            organizer=self.request.organizer,
            pk=self.kwargs.get('id')
        )


class OrganizerOrdersView(OrganizerPermissionRequiredMixin, OrganizerDetailViewMixin, OrdersView):
    permission = 'can_change_organizer_settings'

    def get_object(self, *args, **kwargs):
        return get_object_or_404(
            SepaExport,
            organizer=self.request.organizer,
            pk=self.kwargs.get('id')
        )


class OrganizerExportListView(OrganizerPermissionRequiredMixin, OrganizerDetailViewMixin, ExportListView):
    permission = 'can_change_organizer_settings'

    def get_queryset(self):
        return SepaExport.objects.filter(
            Q(organizer=self.request.organizer) | Q(event__organizer=self.request.organizer)
        ).annotate(
            cnt=Count('sepaexportorder'),
            sum=Sum('sepaexportorder__amount'),
        ).order_by('-datetime')

    def get_unexported(self):
        q_list = []
        today = now().astimezone(self.request.organizer.timezone).today()

        for event in Event.objects.filter(
            organizer=self.request.organizer,
            plugins__contains='pretix_sepadebit'
        ):
            try:
                latest_export_due_date = today + datetime.timedelta(days=int(event.settings.payment_sepadebit_prenotification_days or 0))
            except (TypeError, ValueError):
                continue

            q_list.append(Q(
                order__event=event,
                sepadebit_due__date__lte=latest_export_due_date
            ))

        preselection = OrderPayment.objects.filter(
            provider='sepadebit',
            state=OrderPayment.PAYMENT_STATE_CONFIRMED,
            order__testmode=False,
            sepaexportorder__isnull=True,
        ).annotate(
            refund_amount=Coalesce(
                Subquery(OrderRefund.objects.filter(
                    payment=OuterRef('pk'),
                    state=OrderRefund.REFUND_STATE_DONE,
                ).order_by().values('payment').annotate(s=Sum('amount')).values('s')),
                Decimal('0.00'),
            ),
        )

        if q_list:
            return preselection.filter(reduce(or_, q_list))
        else:
            return OrderPayment.objects.none()
