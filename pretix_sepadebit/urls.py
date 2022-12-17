from django.urls import path, re_path

from . import views

urlpatterns = [
    path('control/organizer/<str:organizer>/sepa/exports/', views.OrganizerExportListView.as_view(),
        name='export'),
    re_path(r'^control/organizer/(?P<organizer>[^/]+)/sepa/exports/(?P<id>\d+).xml$', views.OrganizerDownloadView.as_view(),
        name='download'),
    path('control/organizer/<str:organizer>/sepa/exports/<int:id>/orders/',
        views.OrganizerOrdersView.as_view(),
        name='orders'),

    path('control/event/<str:organizer>/<str:event>/sepa/exports/', views.EventExportListView.as_view(),
        name='export'),
    re_path(r'^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/sepa/exports/(?P<id>\d+).xml$', views.EventDownloadView.as_view(),
        name='download'),
    path('control/event/<str:organizer>/<str:event>/sepa/exports/<int:id>/orders/',
        views.EventOrdersView.as_view(),
        name='orders'),
]
