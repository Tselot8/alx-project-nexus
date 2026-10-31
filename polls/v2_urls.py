from django.urls import path

from . import v2_views as views

app_name = "polls_v2"
urlpatterns = [
    path(
        "polls/<uuid:pk>/ballots/", views.BallotView.as_view(), name="ballots"
    ),
    path(
        "polls/<uuid:pk>/results/", views.ResultsView.as_view(), name="results"
    ),
    path("polls/", views.PollListView.as_view(), name="list"),
    path("polls/mine/", views.MyPollsView.as_view(), name="mine"),
    path("polls/<uuid:pk>/", views.PollDetailView.as_view(), name="detail"),
    path(
        "polls/<uuid:pk>/options/", views.OptionsView.as_view(), name="options"
    ),
    path(
        "polls/<uuid:pk>/options/<uuid:option_id>/",
        views.OptionDetailView.as_view(),
        name="option",
    ),
    path(
        "polls/<uuid:pk>/publish/",
        views.LifecycleView.as_view(),
        {"action": "publish"},
        name="publish",
    ),
    path(
        "polls/<uuid:pk>/close/",
        views.LifecycleView.as_view(),
        {"action": "close"},
        name="close",
    ),
    path(
        "polls/<uuid:pk>/reopen/",
        views.LifecycleView.as_view(),
        {"action": "reopen"},
        name="reopen",
    ),
    path(
        "polls/<uuid:pk>/archive/",
        views.LifecycleView.as_view(),
        {"action": "archive"},
        name="archive",
    ),
    path("polls/<uuid:pk>/share/", views.ShareView.as_view(), name="share"),
    path(
        "polls/<uuid:pk>/share/regenerate/",
        views.ShareView.as_view(http_method_names=["post", "options"]),
        {"regenerate": True},
        name="share-regenerate",
    ),
    path("shares/resolve/", views.ShareResolveView.as_view(), name="resolve"),
    path("categories/", views.CategoryListView.as_view(), name="categories"),
]
