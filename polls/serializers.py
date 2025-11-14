from rest_framework import serializers
from .models import Poll, Option


class OptionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Option
        fields = ['id', 'option_text', 'votes_count']
        read_only_fields = ['id', 'votes_count']


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
            'id', 'question', 'description', 'category', 'is_public',
            'allow_multiple', 'expires_at', 'options'
        ]
        read_only_fields = ['id']

    def create(self, validated_data):
        options_data = validated_data.pop('options')
        user = self.context['request'].user

        poll = Poll.objects.create(created_by=user, **validated_data)

        # Create options
        for opt in options_data:
            Option.objects.create(poll=poll, **opt)

        return poll


class PollDetailSerializer(serializers.ModelSerializer):
    options = OptionSerializer(many=True)

    class Meta:
        model = Poll
        fields = [
            'id', 'question', 'description', 'category', 'created_by',
            'is_public', 'allow_multiple', 'expires_at',
            'created_at', 'updated_at', 'options'
        ]
