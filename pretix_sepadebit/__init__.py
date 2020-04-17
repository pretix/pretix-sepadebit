from django.apps import AppConfig
from django.utils.translation import gettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_sepadebit'
    verbose_name = 'SEPA Direct debit for pretix'

    class PretixPluginMeta:
        name = gettext_lazy('SEPA Direct debit')
        category = 'PAYMENT'
        author = 'Raphael Michel'
        description = gettext_lazy('This plugin adds SEPA direct debit support to pretix')
        visible = True
        version = '1.6.2'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_sepadebit.PluginApp'
