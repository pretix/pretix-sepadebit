import csv
import io
import pytz
from django.utils.translation import gettext as _, gettext_lazy, pgettext_lazy
from pretix.base.exporter import BaseExporter

from pretix_sepadebit.models import SepaExportOrder


class DebitList(BaseExporter):
    identifier = 'debitlistcsv'
    verbose_name = gettext_lazy('List of previous SEPA debits (CSV)')
    category = pgettext_lazy('export_category', 'Order data')
    description = gettext_lazy('Download a spreadsheet of all SEPA debits that have previously been generated and '
                               'exported by the system. To create a new export, use the "SEPA debit" section in '
                               'the main menu.')

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
