from django.dispatch import receiver
from django.urls import resolve, reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.shredder import BaseDataShredder
from django.db.models import Q

from pretix.base.i18n import LazyDate
from i18nfield.strings import LazyI18nString
from functools import reduce
from operator import or_
from django_scopes import scopes_disabled
from django.utils.timezone import now
from pretix.base.signals import (
    register_data_exporters, register_data_shredders,
    register_payment_providers, periodic_task, logentry_display
)
from pretix.base.i18n import language
from datetime import timedelta
from pretix.control.signals import nav_event, nav_organizer
from pretix.base.models import Event
from pretix.base.email import get_email_context
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

def get_todo_sepa_reminders(date):
    q_list = []

    for event in Event.objects.all():
        if event.settings.payment_sepadebit__enabled:
            prenotification_days = int(event.settings.payment_sepadebit_prenotification_days)
            q_list.append(Q(
                reminder=SepaDueDate.REMINDER_OUTSTANDING,
                payment__provider='sepadebit',
                date__lte=now().date()+timedelta(days=prenotification_days))
                )

    if len(q_list)>0:
        qs = reduce(or_, q_list)
        return SepaDueDate.objects.filter(qs).select_related('payment')
    return []

@receiver(signal=periodic_task, dispatch_uid="payment_sepadebit_send_payment_reminders")
def send_payment_reminders(sender, **kwargs):
    with scopes_disabled():
        dd = get_todo_sepa_reminders(date=now().date())

        for due_date in dd:
            order = due_date.payment.order
            event = order.event
            subject = LazyI18nString(event.settings.payment_sepadebit_mail_payment_reminder_subject)
            text = LazyI18nString(event.settings.payment_sepadebit_mail_payment_reminder_text)

            ctx = {
                'event': event,
                'order': order,
                'creditor_id': event.settings.payment_sepadebit_creditor_id,
                'creditor_name': event.settings.payment_sepadebit_creditor_name,
                'account': due_date.payment.info_data['account'],
                'iban': due_date.payment.info_data['iban'],
                'bic': due_date.payment.info_data['bic'],
                'reference': due_date.payment.info_data['reference'],
                'due_date': LazyDate(due_date.date)
            }
            with language(order.locale, event.settings.region):
                due_date.payment.order.send_mail(subject=str(subject), template=text, context=ctx,
                log_entry_type='pretix_sepadebit.payment_reminder.sent.order.email'
                )
                due_date.reminder = SepaDueDate.REMINDER_PROVIDED
                due_date.save()


@receiver(signal=logentry_display, dispatch_uid="payment_sepadebit_send_payment_reminders_logentry")
def payment_reminder_logentry(sender, logentry, **kwargs):
    if logentry.action_type !='pretix_sepadebit.payment_reminder.sent.order.email':
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
