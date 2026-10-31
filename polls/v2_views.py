"""Poll management, scoped shares, atomic ballots and aggregate results."""

from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables
from rest_framework import permissions
from rest_framework.pagination import PageNumberPagination
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from accounts.v2_views import V2View
from . import management
from .models import Category, Option, Poll, PollShareToken
from .policy import authorize_read, public_discovery, share_digest
from .services import get_poll, get_resource_or_404
from .v2_serializers import (
    CategorySerializer,
    DiscoveryInput,
    EmptyInput,
    OptionInput,
    PollCreateInput,
    PollDetail,
    PollInput,
    PollSummary,
    ReopenInput,
    ShareInput,
    MyPollsInput,
    PagingInput,
)


def ordered_polls(queryset, sort):
    ordering = {
        "newest": ["-created_at", "id"],
        "oldest": ["created_at", "id"],
        "closing_soon": [F("expires_at").asc(nulls_last=True), "id"],
    }
    return queryset.order_by(*ordering[sort])


class PollPagination(PageNumberPagination):
    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class PollView(V2View):
    renderer_classes = [JSONRenderer]

    def read_poll(self, request, pk):
        poll = get_resource_or_404(Poll.objects.select_for_update(), pk=pk)
        authorize_read(request.user, poll, request.headers.get("X-Poll-Share"))
        return poll

    def detail(self, poll, status=200):
        return Response(
            PollDetail(poll, context={"request": self.request}).data,
            status=status,
        )

    def parse(self, serializer_class, data):
        serializer = serializer_class(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class PollListView(PollView):
    def get_permissions(self):
        cls = (
            permissions.AllowAny
            if self.request.method in permissions.SAFE_METHODS
            else (permissions.IsAuthenticated)
        )
        return [cls()]

    def get(self, request):
        values = self.parse(DiscoveryInput, request.query_params)
        queryset = public_discovery()
        if values.get("q"):
            queryset = queryset.filter(
                Q(question__icontains=values["q"])
                | Q(description__icontains=values["q"])
            )
        if values.get("category"):
            queryset = queryset.filter(category_id=values["category"])
        now = timezone.now()
        if values.get("status") == "published":
            queryset = queryset.filter(status="published").filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=now)
            )
        elif values.get("status") == "closed":
            queryset = queryset.filter(
                Q(status="closed") | Q(status="published", expires_at__lte=now)
            )
        queryset = ordered_polls(queryset, values.get("sort", "newest"))
        pagination = PollPagination()
        page = pagination.paginate_queryset(queryset, request, self)
        return pagination.get_paginated_response(
            PollSummary(page, many=True, context={"request": request}).data
        )

    def post(self, request):
        data = self.parse(PollCreateInput, request.data)
        data.setdefault("question", "")
        poll = management.create_poll(request.user, data)
        return self.detail(poll, status=201)


class MyPollsView(PollView):
    def get(self, request):
        # Discovery search/filter contract is deliberately shared.
        values = self.parse(MyPollsInput, request.query_params)
        queryset = Poll.objects.filter(created_by=request.user)
        if values.get("q"):
            queryset = queryset.filter(
                Q(question__icontains=values["q"])
                | Q(description__icontains=values["q"])
            )
        if values.get("category"):
            queryset = queryset.filter(category_id=values["category"])
        if values.get("status") == "closed":
            queryset = queryset.filter(
                Q(status="closed")
                | Q(status="published", expires_at__lte=timezone.now())
            )
        elif values.get("status") == "published":
            queryset = queryset.filter(status="published").filter(
                Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now())
            )
        elif values.get("status"):
            queryset = queryset.filter(status=values["status"])
        queryset = ordered_polls(queryset, values.get("sort", "newest"))
        pagination = PollPagination()
        page = pagination.paginate_queryset(queryset, request, self)
        return pagination.get_paginated_response(
            PollSummary(page, many=True, context={"request": request}).data
        )


class PollDetailView(PollView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @transaction.atomic
    def get(self, request, pk):
        return self.detail(self.read_poll(request, pk))

    def patch(self, request, pk):
        data = self.parse(PollInput, request.data)
        poll = management.update_poll(request.user, pk, data)
        return self.detail(poll)

    def delete(self, request, pk):
        management.delete_poll(request.user, pk)
        return Response(status=204)


class OptionsView(PollView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @transaction.atomic
    def get(self, request, pk):
        poll = self.read_poll(request, pk)
        return Response(PollDetail(poll).data["options"])

    def post(self, request, pk):
        data = self.parse(OptionInput, request.data)
        _, option = management.mutate_option(request.user, pk, data)
        return Response(
            {
                "id": str(option.pk),
                "option_text": option.option_text,
            },
            status=201,
        )


class OptionDetailView(PollView):
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @transaction.atomic
    def get(self, request, pk, option_id):
        self.read_poll(request, pk)
        option = get_resource_or_404(
            Option.objects.all(), pk=option_id, poll_id=pk
        )
        return Response(
            {"id": str(option.pk), "option_text": option.option_text}
        )

    def patch(self, request, pk, option_id):
        data = self.parse(OptionInput, request.data)
        _, option = management.mutate_option(
            request.user, pk, data, option_id=option_id
        )
        return Response(
            {"id": str(option.pk), "option_text": option.option_text}
        )

    def delete(self, request, pk, option_id):
        management.mutate_option(
            request.user, pk, option_id=option_id, delete=True
        )
        return Response(status=204)


class LifecycleView(PollView):
    def post(self, request, pk, action):
        serializer = ReopenInput if action == "reopen" else EmptyInput
        data = self.parse(serializer, request.data)
        return self.detail(
            management.transition(request.user, pk, action, data)
        )


class CategoryListView(PollView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        self.parse(PagingInput, request.query_params)
        pagination = PollPagination()
        page = pagination.paginate_queryset(
            Category.objects.order_by("name", "id"), request, self
        )
        return pagination.get_paginated_response(
            CategorySerializer(page, many=True).data
        )


class ShareView(PollView):
    @transaction.atomic
    def get(self, request, pk):
        poll = get_poll(request.user, pk, for_update=True, write=True)
        record = PollShareToken.objects.filter(poll=poll).first()
        return Response(
            {
                "poll_id": str(poll.pk),
                "active": bool(record and record.token_digest),
                "generation": record.generation if record else None,
            }
        )

    @sensitive_variables()
    def post(self, request, pk, regenerate=False):
        self.parse(EmptyInput, request.data)
        poll, record, raw = management.change_share(
            request.user, pk, "regenerate" if regenerate else "issue"
        )
        # Returned once. The client constructs its frontend fragment URL.
        return Response(
            {
                "poll_id": str(poll.pk),
                "generation": record.generation,
                "token": raw,
            },
            status=201,
        )

    def delete(self, request, pk):
        self.parse(EmptyInput, request.data)
        management.change_share(request.user, pk, "revoke")
        return Response(status=204)


class ShareResolveView(PollView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    @sensitive_variables()
    def post(self, request):
        data = self.parse(ShareInput, request.data)
        digest = share_digest(data["token"])
        poll_id = (
            PollShareToken.objects.filter(token_digest=digest)
            .values_list("poll_id", flat=True)
            .first()
        )
        if poll_id is None:
            raise Http404("Not found.")
        poll = get_resource_or_404(
            Poll.objects.select_for_update(), pk=poll_id
        )
        # Revalidate under the same lock as regeneration/revocation.
        authorize_read(None, poll, data["token"])
        if (
            poll.is_public
            or not PollShareToken.objects.filter(
                poll=poll, token_digest=digest
            ).exists()
        ):
            raise Http404("Not found.")
        return Response(
            {
                "poll": PollDetail(poll).data,
                "share": {"poll_id": str(poll.pk), "header": "X-Poll-Share"},
            }
        )


class BallotView(PollView):
    """Only the current user's complete ballot; no withdrawal operation."""

    @transaction.atomic
    def post(self, request, pk):
        from rest_framework.exceptions import ValidationError
        from .ballots import submit
        from .services import PollExpiredError
        from .v2_serializers import BallotInput

        data = self.parse(BallotInput, request.data)
        try:
            ballot, _, _ = submit(request.user, pk, data["option_ids"])
        except PollExpiredError as error:
            raise ValidationError({"poll": [str(error)]}) from None
        return Response(self.ballot_data(ballot))

    @transaction.atomic
    def get(self, request, pk):
        from .ledger import current_selection

        poll = get_poll(request.user, pk, for_update=True)
        ballot, options, submitted_at = current_selection(
            poll, request.user.pk
        )
        return Response(
            {
                "poll_id": str(poll.pk),
                "option_ids": [str(value) for value in sorted(options)],
                "submitted_at": submitted_at,
                "updated_at": ballot.updated_at if ballot else None,
                "submitted": submitted_at is not None,
            }
        )

    def ballot_data(self, ballot):
        return {
            "poll_id": str(ballot.poll_id),
            "option_ids": [
                str(value)
                for value in ballot.selections.order_by(
                    "option_id"
                ).values_list("option_id", flat=True)
            ],
            "submitted_at": ballot.submitted_at,
            "updated_at": ballot.updated_at,
            "submitted": True,
        }


class ResultsView(PollView):
    permission_classes = [permissions.AllowAny]

    @transaction.atomic
    def get(self, request, pk):
        from rest_framework.exceptions import PermissionDenied
        from .ledger import results
        from .policy import can_view_results

        poll = self.read_poll(request, pk)
        if not can_view_results(request.user, poll):
            raise PermissionDenied("Results are not available to you.")
        return Response(results(poll))
