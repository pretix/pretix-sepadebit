import csv
import io
from collections import OrderedDict

import pytz
from django import forms
from django.db.models.functions import Coalesce
from django.utils.translation import gettext as _, gettext_lazy
from pretix.base.exporter import BaseExporter
from pretix.base.models import Order, OrderPosition, Question
from pretix_sepadebit.models import SepaExportOrder


class DebitList(BaseExporter):
    identifier = 'debitlistcsv'
    verbose_name = gettext_lazy('List of SEPA debits (CSV)')

    def render(self, form_data: dict):
        output = io.StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_NONNUMERIC, delimiter=",")
        tz = pytz.timezone(self.event.settings.timezone)

        headers = [
            _('Order code'), _('Order date'), _('Invoices'), _('SEPA export date'), _('Payment amount')
        ]

        writer.writerow(headers)

        qs = SepaExportOrder.objects.filter(export__event=self.event).order_by('export__datetime').select_related(
            'export', 'order'
        ).prefetch_related('order__invoices')
        for seo in qs:
            row = [
                seo.order.code,
                seo.order.datetime.astimezone(tz).strftime('%Y-%m-%d'),
                ', '.join([i.number for i in seo.order.invoices.all()]),
                seo.export.datetime.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S'),
                seo.amount,
            ]
            writer.writerow(row)

        return 'sepaexports.csv', 'text/csv', output.getvalue().encode("utf-8")
