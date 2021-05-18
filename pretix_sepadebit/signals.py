from datetime import date, datetime, timedelta, timezone
from django.db.models import Q
from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from django_scopes import scopes_disabled
from functools import reduce
from i18nfield.strings import LazyI18nString
from operator import or_
from pretix.base.i18n import LazyDate, language
from pretix.base.models import Event
from pretix.base.shredder import BaseDataShredder
from pretix.base.signals import (
    logentry_display, periodic_task, register_data_exporters,
    register_data_shredders, register_payment_providers,
)
from pretix.control.signals import nav_event, nav_organizer
from pretix.base.settings import settings_hierarkey
from django.utils.translation import gettext_noop
from pretix.base.signals import register_mail_placeholders
from pretix.base.email import SimpleFunctionalMailTextPlaceholder, get_email_context

from .payment import SepaDebit, SepaDueDate


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



@receiver(register_mail_placeholders, dispatch_uid="payment_sepadebit_placeholders")
def register_mail_renderers(sender, **kwargs):

    ph = [SimpleFunctionalMailTextPlaceholder(
            'due_date', ['sepadebit_payment'], lambda sepadebit_payment: sepadebit_payment.due.date, sample=date.today()
        ),
        SimpleFunctionalMailTextPlaceholder(
            'account', ['sepadebit_payment'], lambda sepadebit_payment: sepadebit_payment.info_data.get('account', " "), sample="Max Mustermann"
        ),
        SimpleFunctionalMailTextPlaceholder(
            'iban', ['sepadebit_payment'], lambda sepadebit_payment: sepadebit_payment.info_data.get('iban')[0:4] + " **** " + sepadebit_payment.info_data.get('iban')[-4:], sample="DE02 **** 2051"
        ),
        SimpleFunctionalMailTextPlaceholder(
            'bic', ['sepadebit_payment'], lambda sepadebit_payment: sepadebit_payment.info_data.get('bic'), sample="BYLADEM1001"
        ),
        SimpleFunctionalMailTextPlaceholder(
            'reference',
            ['sepadebit_payment'],
            lambda sepadebit_payment: sepadebit_payment.info_data.get('reference'),
            lambda event: f'{event.settings.reference_prefix + "-" if event.settings.reference_prefix else ""}{event.slug.upper()}-XXXXXXX'
        ),
        SimpleFunctionalMailTextPlaceholder(
            'creditor_id', ['sepadebit_payment', "event"], lambda sepadebit_payment, event: event.settings.creditor_id, sample="DE98ZZZ09999999999"
        ),
        SimpleFunctionalMailTextPlaceholder(
            'creditor_name', ['sepadebit_payment', "event"], lambda sepadebit_payment, event: event.settings.creditor_name, sample="DE98ZZZ09999999999"
        )]

    return ph



@receiver(signal=periodic_task, dispatch_uid="payment_sepadebit_send_payment_reminders")
def send_payment_reminders(sender, **kwargs):
    with scopes_disabled():
        dd = SepaDueDate.objects.filter(reminded=False).filter(remind_after__lt=datetime.now(timezone.utc)).filter(payment__order__event__plugins__contains='pretix_sepadebit').select_related('payment').select_related('payment__order').prefetch_related('payment__order__event')

        for due_date in dd:
            order = due_date.payment.order
            event = order.event
            subject = LazyI18nString(event.settings.payment_sepadebit_mail_payment_reminder_subject)
            text = LazyI18nString(event.settings.payment_sepadebit_mail_payment_reminder_text)

            ctx = get_email_context(event=event, order=order, sepa_debit_payment=due_date.payment)

            with language(order.locale, event.settings.region):
                due_date.payment.order.send_mail(
                    subject=str(subject),
                    template=text,
                    context=ctx,
                    log_entry_type='pretix_sepadebit.payment_reminder.sent.order.email'
                )
                due_date.reminded = True
                due_date.save()


@receiver(signal=logentry_display, dispatch_uid="payment_sepadebit_send_payment_reminders_logentry")
def payment_reminder_logentry(sender, logentry, **kwargs):
    if logentry.action_type != 'pretix_sepadebit.payment_reminder.sent.order.email':
        return

    return _('A reminder for the upcoming direct debit due date has been sent to the customer.')


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


settings_hierarkey.add_default(
    "payment_sepadebit_mail_payment_reminder_subject",
    LazyI18nString.from_gettext(
        gettext_noop(
            "Upcomming direct debit due date"
        )
    ), LazyI18nString,
)


settings_hierarkey.add_default(
    "payment_sepadebit_mail_payment_reminder_text",
    LazyI18nString.from_gettext(
        gettext_noop(
            "Hello,\n\n"
            "you ordered a ticket for {event}.\n\n"
            "We will debit your bank account {iban} on or shortly after {due_date}. The payment will appear on your bank statement as {creditor_name} with reference {reference} and creditor identifier {creditor_id}.\n\n"
            "You can change your order details and view the status of your order at\n"
            "{url}\n\n"
            "Best regards,\n"
            "Your {event} team"
        )
    ), LazyI18nString,
)



