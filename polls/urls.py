from django.urls import path
from .views import (
    PollListCreateView,
    PollDetailView,
    OptionCreateView,
    OptionUpdateDeleteView,
    PollResultsView,
    vote_view,
)

urlpatterns = [
    path('', PollListCreateView.as_view(), name='poll-list-create'),
    path('<uuid:pk>/', PollDetailView.as_view(), name='poll-detail'),

    # Options
    path('<uuid:poll_id>/options/', OptionCreateView.as_view(), name='option-create'),
    path('options/<uuid:pk>/', OptionUpdateDeleteView.as_view(), name='option-update-delete'),

    # Results
    path('<uuid:poll_id>/results/', PollResultsView.as_view(), name='poll-results'),
    path('<uuid:poll_id>/vote/<uuid:option_id>/', vote_view, name='cast-vote'),

]
