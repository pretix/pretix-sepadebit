from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/exports/$', views.ExportListView.as_view(),
        name='export'),
    url(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/exports/(?P<id>\d+).xml$', views.DownloadView.as_view(),
        name='download'),
]
