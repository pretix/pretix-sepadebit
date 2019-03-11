from django.apps import AppConfig
from django.utils.translation import ugettext_lazy


class PluginApp(AppConfig):
    name = 'pretix_sepadebit'
    verbose_name = 'SEPA Direct debit for pretix'

    class PretixPluginMeta:
        name = ugettext_lazy('SEPA Direct debit for pretix')
        author = 'Raphael Michel'
        description = ugettext_lazy('This plugin adds SEPA direct debit support to pretix')
        visible = True
        version = '1.5.0'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_sepadebit.PluginApp'
