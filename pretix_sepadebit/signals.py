from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.shredder import BaseDataShredder
from pretix.base.signals import (
    register_data_exporters, register_data_shredders,
    register_payment_providers,
)
from pretix.control.signals import nav_event, nav_organizer

from .payment import SepaDebit


@receiver(register_payment_providers, dispatch_uid="payment_sepadebit")
def register_payment_provider(sender, **kwargs):
    return SepaDebit


@receiver(nav_event, dispatch_uid="payment_sepadebit_nav")
def control_nav_import(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_event_permission(request.organizer, request.event, 'can_change_orders', request=request):
        return []
    return [
        {
            'label': _('SEPA debit'),
            'url': reverse('plugins:pretix_sepadebit:export', kwargs={
                'event': request.event.slug,
                'organizer': request.event.organizer.slug,
            }),
            'active': (url.namespace == 'plugins:pretix_sepadebit' and url.url_name == 'export'),
            'icon': 'bank',
        }
    ]


@receiver(nav_organizer, dispatch_uid="payment_sepadebit_organav")
def control_nav_orga_sepadebit(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.user.has_organizer_permission(request.organizer, 'can_change_organizer_settings', request=request):
        return []
    if not request.organizer.events.filter(plugins__icontains='pretix_sepadebit'):
        return []
    return [
        {
            'label': _('SEPA debit'),
            'url': reverse('plugins:pretix_sepadebit:export', kwargs={
                'organizer': request.organizer.slug,
            }),
            'active': (url.namespace == 'plugins:pretix_sepadebit' and url.url_name == 'export'),
            'icon': 'bank',
        }
    ]


@receiver(register_data_exporters, dispatch_uid="payment_sepadebit_export_csv")
def register_csv(sender, **kwargs):
    from .exporters import DebitList
    return DebitList


class PaymentLogsShredder(BaseDataShredder):
    verbose_name = _('SEPA debit history')
    identifier = 'sepadebit_history'
    description = _('This will remove previously exported SEPA XML files containing banking information.')

    def generate_files(self):
        for f in self.event.sepa_exports.all():
            yield (
                'sepadebit/{}-{}.xml'.format(self.event.slug.upper(), f.datetime.strftime('%Y-%m-%d-%H-%M-%S')),
                'text/plain',
                f.xmldata
            )

    def shred_data(self):
        self.event.sepa_exports.update(xmldata="<shredded></shredded>")


@receiver(register_data_shredders, dispatch_uid="sepadebit_shredders")
def register_shredder(sender, **kwargs):
    return [
        PaymentLogsShredder,
    ]
