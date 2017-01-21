from django.dispatch import receiver
from django.urls import resolve
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

from pretix.base.signals import register_payment_providers
from pretix.control.signals import nav_event

from .payment import SepaDebit


@receiver(register_payment_providers, dispatch_uid="payment_sepadebit")
def register_payment_provider(sender, **kwargs):
    return SepaDebit


@receiver(nav_event, dispatch_uid="payment_sepadebit_nav")
def control_nav_import(sender, request=None, **kwargs):
    url = resolve(request.path_info)
    if not request.eventperm.can_change_orders:
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
