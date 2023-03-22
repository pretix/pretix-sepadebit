import csv
import io
from collections import OrderedDict

import pytz
from django.utils.timezone import now
from django.utils.translation import gettext as _, gettext_lazy, pgettext_lazy
from pretix.base.exporter import BaseExporter, ListExporter
from pretix.base.timeframes import DateFrameField, resolve_timeframe_to_datetime_start_inclusive_end_exclusive

from pretix_sepadebit.models import SepaExportOrder


class DebitList(ListExporter):
    identifier = 'debitlistcsv'
    verbose_name = gettext_lazy('List of previous SEPA debits')
    category = pgettext_lazy('export_category', 'Order data')
    description = gettext_lazy('Download a spreadsheet of all SEPA debits that have previously been generated and '
                               'exported by the system. To create a new export, use the "SEPA debit" section in '
                               'the main menu.')

    @property
    def additional_form_fields(self):
        return OrderedDict(
            [
                ('date_range',
                 DateFrameField(
                     label=_('Export date'),
                     include_future_frames=False,
                     required=False,
                 )),
            ]
        )

    def iterate_list(self, form_data):
        tz = self.timezone

        headers = [
            _('Event slug'), _('Event name'),
            _('Order code'), _('Order date'),
            _('Invoices'),
            _('SEPA export date'),
            _('Payment amount'),
        ]

        yield headers

        qs = SepaExportOrder.objects.filter(export__event__in=self.events).order_by('export__datetime').select_related(
            'export', 'order', 'order__event'
        ).prefetch_related('order__invoices')

        if form_data.get('date_range'):
            dt_start, dt_end = resolve_timeframe_to_datetime_start_inclusive_end_exclusive(now(), form_data['date_range'], self.timezone)
            if dt_start:
                qs = qs.filter(export__datetime__gte=dt_start)
            if dt_end:
                qs = qs.filter(export__datetime__lt=dt_end)

        for seo in qs:
            row = [
                seo.order.event.slug,
                str(seo.order.event.name),
                seo.order.code,
                seo.order.datetime.astimezone(tz).strftime('%Y-%m-%d'),
                ', '.join([i.number for i in seo.order.invoices.all()]),
                seo.export.datetime.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
                seo.amount,
            ]
            yield row

    def get_filename(self):
        return 'sepaexports'