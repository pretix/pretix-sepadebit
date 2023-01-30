from django.apps import AppConfig
from django.utils.translation import gettext_lazy
from . import __version__


class PluginApp(AppConfig):
    name = 'pretix_sepadebit'
    verbose_name = 'SEPA Direct debit for pretix'

    class PretixPluginMeta:
        name = gettext_lazy('SEPA Direct debit')
        category = 'PAYMENT'
        author = 'Raphael Michel'
        description = gettext_lazy('This plugin adds SEPA direct debit support to pretix')
        visible = True
        version = __version__
        compatibility = "pretix>=4.16.0"

    def ready(self):
        from . import signals  # NOQA


