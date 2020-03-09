import json
import logging
from collections import OrderedDict
from datetime import timedelta
from typing import Union

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.validators import RegexValidator
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from localflavor.generic.forms import BICFormField, IBANFormField
from pretix.base.models import Order, OrderPayment, OrderRefund, Quota
from pretix.base.payment import BasePaymentProvider, PaymentException

logger = logging.getLogger(__name__)


class SepaDebit(BasePaymentProvider):
    identifier = 'sepadebit'
    verbose_name = _('SEPA debit')
    abort_pending_allowed = True

    @property
    def test_mode_message(self):
        return _('Test mode payments will only be debited if you submit a file created in test mode to your bank.')

    @property
    def settings_form_fields(self):
        d = OrderedDict(
            [
                ('ack',
                 forms.BooleanField(
                     label=_('I have understood that I need to regularly create SEPA XML export files and transfer '
                             'them to my bank in order to have my bank collect the customer payments.'),
                     required=True,
                 )),
                ('creditor_name',
                 forms.CharField(
                     label=_('Creditor name'),
                     max_length=70,
                 )),
                ('creditor_iban',
                 IBANFormField(
                     label=_('Creditor IBAN'),
                 )),
                ('creditor_bic',
                 BICFormField(
                     label=_('Creditor BIC'),
                 )),
                ('creditor_id',
                 forms.CharField(
                     label=_('Creditor ID'),
                     validators=[
                         RegexValidator(
                             regex=(r"^[a-zA-Z]{2,2}[0-9]{2,2}([A-Za-z0-9]|[\+|\?|/|\-|:|\(|\)|\.|,|']){3,3}"
                                    r"([A-Za-z0-9]|[\+|\?|/|\-|:|\(|\)|\.|,|']){1,28}$"),
                             message=_('This must be a valid SEPA creditor ID.'),
                         )
                     ],
                     max_length=28
                 )),
                ('reference_prefix',
                 forms.CharField(
                     label=_('Mandate reference prefix'),
                     validators=[
                         RegexValidator(
                             regex=r"^[a-zA-Z0-9',.:+\-/\(\)?]+$",
                             message=_("This may only contain letters, numbers, and the following special "
                                       "characters: ' , . : + - / ( ) ?")
                         ),
                     ],
                     required=False,
                     help_text=_('We will use this string and append the event slug and the order code to build a '
                                 'unique SEPA mandate reference.'),
                     max_length=35 - settings.ENTROPY['order_code'] - 2 - len(self.event.slug)
                 )),
                ('prenotification_days',
                 forms.IntegerField(
                     label=_('Pre-notification time'),
                     help_text=_('Number of days between the placement of the order and the due date of the direct '
                                 'debit. Depending on your legislation and your bank rules, you might be required to '
                                 'hand in a debit at least 5 days before the due date at your bank and you might even '
                                 'be required to inform the customer at least 14 days beforehand. We recommend '
                                 'configuring at least 7 days.'),
                     min_value=1
                 )),
            ] + list(super().settings_form_fields.items())
        )
        d.move_to_end('_enabled', last=False)
        return d

    def settings_content_render(self, request):
        box = "<div class='alert alert-info'>%s</div>" % (
            _('If you activate this payment method, SEPA direct debit mandates will be collected via an online form. '
              'Depending on your legislation, it might be necessary to collect them on paper (currently not '
              'supported) to exclude the risk of charge backs. SEPA debit payments will be immediately marked as paid '
              'in the shop, so please mark it as unpaid and contact the user if any charge backs occur or the charge '
              'fails due to insufficient funds.'),
        )
        if '{payment_info}' not in str(request.event.settings.mail_text_order_paid):
            box += "<div class='alert alert-danger'>%s</div>" % (
                _('The placeholder <code>{payment_info}</code> is not present in your configured email template for '
                  'order payment notifications. This is legally required as it includes the mandate reference and the '
                  'due date.'),
            )
        return box

    def payment_is_valid_session(self, request):
        return (
            request.session.get('payment_sepa_account', '') != '' and
            request.session.get('payment_sepa_iban', '') != '' and
            request.session.get('payment_sepa_bic', '') != ''
        )

    @property
    def payment_form_fields(self):
        return OrderedDict([
            ('account', forms.CharField(label=_('Account holder'))),
            ('iban', IBANFormField(label=_('IBAN'))),
            ('bic', BICFormField(label=_('BIC'))),
            ('mandate', forms.BooleanField(
                label=_('I hereby grant the SEPA direct debit mandate for this order (see below)'))),
        ])

    def payment_prepare(self, request: HttpRequest, payment: OrderPayment):
        return self.checkout_prepare(request, None)

    def checkout_prepare(self, request, cart):
        form = self.payment_form(request)
        if form.is_valid():
            request.session['payment_sepa_account'] = form.cleaned_data['account']
            request.session['payment_sepa_iban'] = form.cleaned_data['iban']
            request.session['payment_sepa_bic'] = form.cleaned_data['bic']
            return True
        return False

    def payment_form_render(self, request) -> str:
        template = get_template('pretix_sepadebit/checkout_payment_form.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'form': self.payment_form(request),
            'date': self._due_date()
        }
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretix_sepadebit/checkout_payment_confirm.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'iban': request.session['payment_sepa_iban'],
            'date': self._due_date()
        }
        return template.render(ctx)

    def execute_payment(self, request: HttpRequest, payment: OrderPayment):
        due_date = self._due_date()
        ref = '%s-%s' % (self.event.slug.upper(), payment.order.code)
        if self.settings.reference_prefix:
            ref = self.settings.reference_prefix + "-" + ref

        try:
            payment.info_data = {
                'account': request.session['payment_sepa_account'],
                'iban': request.session['payment_sepa_iban'],
                'bic': request.session['payment_sepa_bic'],
                'reference': ref,
                'date': due_date.strftime("%Y-%m-%d")
            }
            payment.confirm(mail_text=self.order_pending_mail_render(payment.order))
        except Quota.QuotaExceededException as e:
            raise PaymentException(str(e))
        finally:
            del request.session['payment_sepa_account']
            del request.session['payment_sepa_iban']
            del request.session['payment_sepa_bic']

    def payment_pending_render(self, request: HttpRequest, payment: OrderPayment):
        template = get_template('pretix_sepadebit/pending.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings}
        return template.render(ctx)

    def payment_control_render(self, request: HttpRequest, payment: OrderPayment):
        template = get_template('pretix_sepadebit/control.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'payment_info': payment.info_data,
            'order': payment.order,
        }
        return template.render(ctx)

    def order_pending_mail_render(self, order) -> str:
        ref = '%s-%s' % (self.event.slug.upper(), order.code)
        if self.settings.reference_prefix:
            ref = self.settings.reference_prefix + "-" + ref

        template = get_template('pretix_sepadebit/mail.txt')
        ctx = {
            'event': self.event,
            'order': order,
            'creditor_id': self.settings.creditor_id,
            'creditor_name': self.settings.creditor_name,
            'reference': ref,
            'date': self._due_date(order)
        }
        return template.render(ctx)

    def _due_date(self, order=None):
        startdate = order.datetime.date() if order else now().date()
        return startdate + timedelta(days=self.settings.get('prenotification_days', as_type=int))

    def shred_payment_info(self, obj: Union[OrderPayment, OrderRefund]):
        d = obj.info_data
        d['account'] = '█'
        d['iban'] = '█'
        d['bic'] = '█'
        d['_shredded'] = True
        obj.info_data = d
        obj.save(update_fields=['info'])
