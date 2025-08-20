from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig, PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID
except ImportError:
    raise RuntimeError("Please use pretix 2025.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    name = "pretix_sepadebit"
    verbose_name = "SEPA Direct debit for pretix"

    class PretixPluginMeta:
        name = gettext_lazy("SEPA Direct debit")
        category = "PAYMENT"
        author = "Raphael Michel"
        description = gettext_lazy(
            "This plugin adds SEPA direct debit support to pretix"
        )
        visible = True
        version = __version__
        compatibility = "pretix>=4.18.0.dev0"
        level = PLUGIN_LEVEL_EVENT_ORGANIZER_HYBRID

    def ready(self):
        from . import signals  # NOQA
