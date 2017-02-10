from django.apps import AppConfig


class PluginApp(AppConfig):
    name = 'pretix_sepadebit'
    verbose_name = 'SEPA Direct debit for pretix'

    class PretixPluginMeta:
        name = 'SEPA Direct debit for pretix'
        author = 'Raphael Michel'
        description = 'This plugin adds SEPA direct debit support to pretix'
        visible = True
        version = '1.0.2'

    def ready(self):
        from . import signals  # NOQA


default_app_config = 'pretix_sepadebit.PluginApp'
