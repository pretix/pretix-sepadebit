from typing import Union

import logging
from collections import OrderedDict
from datetime import date, timedelta
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.http import HttpRequest
from django.template.loader import get_template
from django.utils.formats import date_format
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from i18nfield.forms import I18nFormField, I18nTextarea, I18nTextInput
from localflavor.generic.forms import BICFormField, IBANFormField
from localflavor.generic.validators import BICValidator, IBANValidator
from pretix.base.email import get_available_placeholders
from pretix.base.forms import PlaceholderValidator
from pretix.base.models import OrderPayment, OrderRefund, Quota
from pretix.base.payment import (
    BasePaymentProvider, PaymentException, PaymentProviderForm,
)

from pretix_sepadebit.models import SepaDueDate

logger = logging.getLogger(__name__)


class NotBlocklisted:
    def __init__(self, pp):
        self.pp = pp

    def __call__(self, value):
        if any(value.replace(' ', '').startswith(b) for b in (self.pp.settings.iban_blocklist or '').splitlines() if b):
            raise ValidationError(_('Direct debit is not allowed for this IBAN, please get in touch with the event organizer or '
                                    'choose a different payment method.'))
        return value


class SEPAPaymentProviderForm(PaymentProviderForm):
    def clean(self):
        from .bicdata import DATA

        d = super().clean()

        if d.get('iban'):
            iban_without_checksum = d['iban'][0:2] + 'XX' + d['iban'][4:]
            for k in range(6, 15):
                if iban_without_checksum[:k] in DATA:
                    correct_bic = DATA[iban_without_checksum[:k]]
                    input_bic = d.get('bic', '')
                    if len(input_bic) < len(correct_bic):
                        input_bic += 'XXX'
                    if correct_bic != input_bic:
                        raise ValidationError(
                            _('The BIC number {bic} does not match the IBAN. Please double, check your banking '
                              'details. According to our data, the correct BIC would be {correctbic}.').format(
                                bic=input_bic, correctbic=correct_bic
                            )
                        )

        return d


class SepaDebit(BasePaymentProvider):
    identifier = 'sepadebit'
    verbose_name = _('SEPA debit')
    abort_pending_allowed = True
    payment_form_class = SEPAPaymentProviderForm

    @property
    def test_mode_message(self):
        return _('Test mode payments will only be debited if you submit a file created in test mode to your bank.')

    def _set_field_placeholders(self, form_dict, fn, base_parameters, extras=[]):
        phs = [
            "{%s}" % p
            for p in sorted(
                get_available_placeholders(self.event, base_parameters).keys()
            )
        ] + extras
        ht = _("Available placeholders: {list}").format(list=", ".join(phs))
        if form_dict[fn].help_text:
            form_dict[fn].help_text += " " + str(ht)
        else:
            form_dict[fn].help_text = ht
        form_dict[fn].validators.append(PlaceholderValidator(phs))

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
                ('iban_blocklist', forms.CharField(
                    label=_('IBAN blocklist'),
                    required=False,
                    widget=forms.Textarea,
                    help_text='{}<div class="alert alert-legal">{}</div>'.format(
                        _('Put one IBAN or IBAN prefix per line. The system will not allow any of these IBANs.  Useful '
                          'e.g. if you had lots of failed payments already from a specific person. You can also list '
                          'country codes such as "GB" if you never want to accept IBANs from a specific country.'),
                        _('Adding whole countries to your blocklist is considered SEPA discrimination, illegal in '
                          'most countries and can be cause for hefty fines from government watchdogs.')
                    )
                )),
                ('earliest_due_date',
                 forms.DateField(
                     label=_('Earliest debit due date'),
                     help_text=_('Earliest date the direct debit can be due. '
                                 'This date is used as the direct debit due date if the order date plus '
                                 'pre-notification time would result in a due date earlier than this. Customers with '
                                 'orders using the earliest due date will receive an email reminding them about the '
                                 'upcoming charge based on the configured pre-notification days.'),
                     required=False,
                     widget=forms.widgets.DateInput(attrs={'class': 'datepickerfield'})
                 )),
                ('pre_notification_mail_subject',
                 I18nFormField(
                     label=_("Pre-notification mail subject"),
                     help_text=_('The subject of the notification email. '
                                 'This email is only sent if the earliest debit due date option is used.'),
                     required=False,
                     widget=I18nTextInput,
                     widget_kwargs={
                         'attrs': {
                             'data-display-dependency': '#id_payment_sepadebit_earliest_due_date'
                         }
                     },
                 )),
                ('pre_notification_mail_body',
                 I18nFormField(
                     label=_("Pre-notification mail body"),
                     help_text=_('The body of the notification email. '
                                 'This email is only sent if the earliest debit due date option is used.'),
                     required=False,
                     widget=I18nTextarea,
                     widget_kwargs={
                         'attrs': {
                             'data-display-dependency': '#id_payment_sepadebit_earliest_due_date'
                         }
                     },
                 ))
            ] + list(super().settings_form_fields.items())
        )
        d.move_to_end('_enabled', last=False)

        self._set_field_placeholders(
            d, "pre_notification_mail_subject", ["event", "order", "sepadebit_payment"], []
        )
        self._set_field_placeholders(
            d, "pre_notification_mail_body", ["event", "order", "sepadebit_payment"], []
        )
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
            request.session.get('payment_sepa_account', '') != ''
            and request.session.get('payment_sepa_iban', '') != ''
            and request.session.get('payment_sepa_bic', '') != ''
        )

    def settings_form_clean(self, cleaned_data):
        super().settings_form_clean(cleaned_data)

        if cleaned_data.get('payment_sepadebit_earliest_due_date'):
            if not (cleaned_data.get('payment_sepadebit_pre_notification_mail_subject') and cleaned_data.get('payment_sepadebit_pre_notification_mail_body')):
                raise ValidationError(_("Due date reminder email fields are required if earliest due date feature is used."))

    @property
    def payment_form_fields(self):
        return OrderedDict([
            ('account', forms.CharField(label=_('Account holder'))),
            ('iban', IBANFormField(label=_('IBAN'), validators=[NotBlocklisted(self)])),
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
        due_date, reminded = self._due_date_reminded()
        ref = '%s-%s' % (self.event.slug.upper(), payment.order.code)
        if self.settings.reference_prefix:
            ref = self.settings.reference_prefix + "-" + ref

        try:
            payment.info_data = {
                'account': request.session['payment_sepa_account'],
                'iban': request.session['payment_sepa_iban'],
                'bic': request.session['payment_sepa_bic'],
                'reference': ref,
            }

            # add current time to due_date for remind after to take pressure of the cron job
            due = SepaDueDate.objects.update_or_create(
                payment=payment,
                defaults={
                    'date': due_date,
                    'reminded': reminded,
                    'remind_after': now().astimezone(self.event.timezone).replace(year=due_date.year, month=due_date.month, day=due_date.day)
                }
            )[0]

            payment.confirm(mail_text=self.order_pending_mail_render(payment.order))
        except Quota.QuotaExceededException as e:
            due.delete()
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
            'payment_due_date': payment.sepadebit_due.date if hasattr(payment, 'sepadebit_due') else None
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
        due_date = self._due_date_reminded(order)
        return due_date[0]

    def _due_date_reminded(self, order=None):
        startdate = order.datetime.date() if order else now().date()
        relative_due_date = startdate + timedelta(days=self.settings.get('prenotification_days', as_type=int))

        earliest_due_date = self.settings.get('earliest_due_date', as_type=date)

        if earliest_due_date:
            if earliest_due_date > relative_due_date:
                return earliest_due_date, False

        return relative_due_date, True

    def shred_payment_info(self, obj: Union[OrderPayment, OrderRefund]):
        d = obj.info_data
        d['account'] = '█'
        d['iban'] = '█'
        d['bic'] = '█'
        d['_shredded'] = True
        obj.info_data = d
        obj.save(update_fields=['info'])

    @staticmethod
    def norm(s):
        return s.strip().upper().replace(" ", "")

    def execute_refund(self, refund: OrderRefund):
        if refund.payment.sepaexportorder_set.exists():
            refund.info_data = {
                'payer': refund.payment.info_data['account'],  # Use payer to keep it compatible with the banktransfer-refunds
                'iban': self.norm(refund.payment.info_data['iban']),
                'bic': self.norm(refund.payment.info_data['bic']),
            }
            refund.save(update_fields=["info"])
        else:
            refund.done()

    def payment_refund_supported(self, payment: OrderPayment) -> bool:
        if not payment.sepaexportorder_set.exists():
            return True

        if not all(payment.info_data.get(key) for key in ("account", "iban", "bic")):
            return False
        try:
            IBANValidator()(self.norm(payment.info_data['iban']))
            BICValidator()(self.norm(payment.info_data['bic']))
        except ValidationError:
            return False
        else:
            return True

    def payment_partial_refund_supported(self, payment: OrderPayment) -> bool:
        return self.payment_refund_supported(payment)

    def render_invoice_text(self, order, payment: OrderPayment) -> str:
        ref = '%s-%s' % (self.event.slug.upper(), order.code)
        if self.settings.reference_prefix:
            ref = self.settings.reference_prefix + "-" + ref
        t = _("We will debit the total amount of this order from your bank account by "
              "direct debit on or shortly after %(date)s.") % {
            'date': date_format(self._due_date(order), 'SHORT_DATE_FORMAT')
        }
        t += " "
        t += _("This payment will appear on your bank statement as %(creditor_name)s with "
               "mandate reference %(reference)s and creditor ID %(id)s.") % {
            'reference': ref,
            'id': self.settings.creditor_id,
            'creditor_name': self.settings.creditor_name,
        }
        return t
