import json
import logging
from collections import OrderedDict

from django import forms
from django.conf import settings
from django.contrib import messages
from django.core.validators import RegexValidator
from django.template.loader import get_template
from django.utils.translation import ugettext_lazy as _
from localflavor.generic.forms import BICFormField, IBANFormField

from pretix.base.models import Quota
from pretix.base.payment import BasePaymentProvider

logger = logging.getLogger(__name__)


class PaymentForm(forms.Form):
    account = forms.CharField(label=_('Account holder'))
    iban = IBANFormField(label=_('IBAN'))
    bic = BICFormField(label=_('BIC'))
    confirm = forms.BooleanField(label=_('I hereby grant the SEPA direct debit mandate for this order (see below)'))


class SepaDebit(BasePaymentProvider):
    identifier = 'sepadebit'
    verbose_name = _('SEPA debit')

    @property
    def settings_form_fields(self):
        return OrderedDict(
            list(super().settings_form_fields.items()) + [
                ('creditor_name',
                 forms.CharField(
                     label=_('Creditor name'),
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
            ]
        )

    def settings_content_render(self, request):
        return "<div class='alert alert-info'>%s</div>" % (
            _('If you activate this payment method, SEPA direct debit mandates will be collected via an online form. '
              'Depending on your legislation, it might be necessary to collect them on paper (currently not '
              'supported) to exclude the risk of charge backs. SEPA debit payments will be immediately marked as paid '
              'in the shop, so please mark it as unpaid and contact the user if any charge backs occur or the charge '
              'fails due to insufficient funds.'),
        )

    def payment_is_valid_session(self, request):
        return (
            request.session.get('payment_sepa_account', '') != '' and
            request.session.get('payment_sepa_iban', '') != '' and
            request.session.get('payment_sepa_bic', '') != ''
        )

    def _payment_form(self, request):
        return PaymentForm(data=request.POST if request.method == 'POST' else None)

    def order_prepare(self, request, order):
        return self.checkout_prepare(request, None)

    def checkout_prepare(self, request, cart):
        form = self._payment_form(request)
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
            'form': self._payment_form(request)
        }
        return template.render(ctx)

    def checkout_confirm_render(self, request) -> str:
        template = get_template('pretix_sepadebit/checkout_payment_confirm.html')
        ctx = {
            'request': request,
            'event': self.event,
            'settings': self.settings,
            'iban': request.session['payment_sepa_iban']
        }
        return template.render(ctx)

    def order_can_retry(self, order):
        return self._is_still_available()

    def payment_perform(self, request, order) -> str:
        from pretix.base.services.orders import mark_order_paid

        ref = '%s-%s' % (self.event.slug.upper(), order.code)
        if self.settings.reference_prefix:
            ref = self.settings.reference_prefix + "-" + ref

        try:
            mark_order_paid(order, 'sepadebit', json.dumps({
                'account': request.session['payment_sepa_account'],
                'iban': request.session['payment_sepa_iban'],
                'bic': request.session['payment_sepa_bic'],
                'reference': ref
            }))
        except Quota.QuotaExceededException as e:
            messages.error(request, str(e))
        else:
            del request.session['payment_sepa_account']
            del request.session['payment_sepa_iban']
            del request.session['payment_sepa_bic']

    def order_pending_render(self, request, order) -> str:
        if order.payment_info:
            payment_info = json.loads(order.payment_info)
        else:
            payment_info = None
        template = get_template('pretix_sepadebit/pending.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings,
               'order': order, 'payment_info': payment_info}
        return template.render(ctx)

    def order_control_render(self, request, order) -> str:
        if order.payment_info:
            payment_info = json.loads(order.payment_info)
            if 'amount' in payment_info:
                payment_info['amount'] /= 100
        else:
            payment_info = None
        template = get_template('pretix_sepadebit/control.html')
        ctx = {'request': request, 'event': self.event, 'settings': self.settings,
               'payment_info': payment_info, 'order': order}
        return template.render(ctx)

    def order_pending_mail_render(self, order) -> str:
        if order.payment_info:
            payment_info = json.loads(order.payment_info)
        else:
            payment_info = None
        template = get_template('pretix_sepadebit/order_pending.txt')
        ctx = {
            'event': self.event,
            'order': order,
            'creditor_id': self.settings.creditor_id,
            'iban': payment_info['iban'],
            'reference': payment_info['reference'],
        }
        return template.render(ctx)
