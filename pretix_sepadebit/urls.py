from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^control/organizer/(?P<organizer>[^/]+)/sepa/exports/$', views.OrganizerExportListView.as_view(),
        name='export'),
    url(r'^control/organizer/(?P<organizer>[^/]+)/sepa/exports/(?P<id>\d+).xml$', views.OrganizerDownloadView.as_view(),
        name='download'),
    url(r'^control/organizer/(?P<organizer>[^/]+)/sepa/exports/(?P<id>\d+)/orders/$',
        views.OrganizerOrdersView.as_view(),
        name='orders'),

    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sepa/exports/$', views.EventExportListView.as_view(),
        name='export'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sepa/exports/(?P<id>\d+).xml$', views.EventDownloadView.as_view(),
        name='download'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sepa/exports/(?P<id>\d+)/orders/$',
        views.EventOrdersView.as_view(),
        name='orders'),
]
