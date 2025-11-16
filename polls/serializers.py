from rest_framework import serializers, generics, permissions
from .models import Poll, Option
from django.db.models import Count

class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'option_text', 'votes_count']
        read_only_fields = ['id', 'votes_count']


class OptionCreateView(generics.CreateAPIView):
    serializer_class = OptionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        poll_id = self.kwargs["poll_id"]
        poll = get_object_or_404(Poll, id=poll_id)
        serializer.save(poll_id=poll_id)


class PollSerializer(serializers.ModelSerializer):
    class Meta:
        model = Poll
        fields = [
            'id', 'question', 'description', 'category', 'created_by',
            'is_public', 'allow_multiple', 'expires_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']


class PollCreateSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True)

    class Meta:
        model = Poll
        fields = [
            'id', 'question', 'description', 'category', 
            'created_by', 'is_public', 'allow_multiple',
            'expires_at', 'options'
        ]
        read_only_fields = ['id', 'created_by']

    def create(self, validated_data):
        options_data = validated_data.pop('options')
        poll = Poll.objects.create(**validated_data)
        
        # Create linked options
        for opt in options_data:
            Option.objects.create(poll=poll, **opt)
        
        return poll

class PollDetailSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True, read_only=True)

    class Meta:
        model = Poll
        fields = [
            'id', 'question', 'description', 'category', 'created_by',
            'is_public', 'allow_multiple', 'expires_at',
            'created_at', 'updated_at', 'options'
        ]

class OptionResultSerializer(serializers.ModelSerializer):
    votes = serializers.IntegerField()

    percentage = serializers.SerializerMethodField()

    class Meta:
        model = Option
        fields = ["id", "option_text", "votes", "percentage"]

    def get_percentage(self, obj):
        total = self.context.get("total_votes", 0)
        if total == 0:
            return 0
        return round((obj.votes / total) * 100, 2)


class PollResultsSerializer(serializers.ModelSerializer):
    options = OptionResultSerializer(many=True)
    total_votes = serializers.IntegerField()

    class Meta:
        model = Poll
        fields = [
            "id",
            "question",
            "description",
            "category",
            "created_by",
            "allow_multiple",
            "is_public",
            "expires_at",
            "created_at",
            "updated_at",
            "total_votes",
            "options"
        ]
