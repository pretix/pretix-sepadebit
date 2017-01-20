# Register your receivers here
from django.dispatch import receiver

from pretix.base.signals import register_payment_providers

from .payment import SepaDebit


@receiver(register_payment_providers, dispatch_uid="payment_sepadebit")
def register_payment_provider(sender, **kwargs):
    return SepaDebit
