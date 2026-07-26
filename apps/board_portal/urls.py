from django.urls import path

from . import views


urlpatterns = [
    path("", views.nursing_board_dashboard, name="board_nursing_dashboard"),
    path("meetings/", views.nursing_board_meetings, name="board_nursing_meetings"),
    path("meetings/<int:meeting_id>/", views.nursing_board_meeting_detail, name="board_nursing_meeting_detail"),
    path("board-packs/<int:pack_id>/", views.nursing_board_pack_reader, name="board_nursing_board_pack"),
    path("ai/chat/", views.nursing_board_ai_chat, name="board_nursing_ai_chat"),
    path("papers/", views.nursing_board_papers, name="board_nursing_papers"),
    path("decision-queue/", views.nursing_board_decision_queue, name="board_nursing_decision_queue"),
    path("committees/", views.nursing_board_committees, name="board_nursing_committees"),
    path("committees/registration/", views.nursing_board_committee, {"slug": "registration"}, name="board_nursing_committee_registration"),
    path("committees/education/", views.nursing_board_committee, {"slug": "education"}, name="board_nursing_committee_education"),
    path("committees/standards/", views.nursing_board_committee, {"slug": "standards"}, name="board_nursing_committee_standards"),
    path("committees/conduct/", views.nursing_board_committee, {"slug": "conduct"}, name="board_nursing_committee_conduct"),
    path("committees/<slug:slug>/", views.nursing_board_committee, name="board_nursing_committee"),
    path("actions/", views.nursing_board_actions, name="board_nursing_actions"),
    path("minutes/", views.nursing_board_minutes, name="board_nursing_minutes"),
    path("library/", views.nursing_board_library, name="board_nursing_library"),
    path("risk/", views.nursing_board_risk, name="board_nursing_risk"),
    path("profile/", views.nursing_board_profile, name="board_nursing_profile"),
]
