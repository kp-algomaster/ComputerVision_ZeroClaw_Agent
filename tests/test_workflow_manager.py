import pytest
from unittest.mock import AsyncMock, Mock, patch
from cv_agent.core.workflow_manager import WorkflowManager

@pytest.mark.asyncio
async def test_submit_workflow():
    manager = WorkflowManager()
    manager.base_url = "http://localhost:7862"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = Mock()
        mock_resp.json.return_value = {"runId": "test-1234"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = await manager.submit_workflow("Test workflow")
        assert result["runId"] == "test-1234"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"] == {"description": "Test workflow"}

@pytest.mark.asyncio
async def test_resolve_checkpoint():
    manager = WorkflowManager()
    manager.base_url = "http://localhost:7862"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_resp = Mock()
        mock_resp.json.return_value = {"status": "ok"}
        mock_resp.raise_for_status.return_value = None
        mock_post.return_value = mock_resp

        result = await manager.resolve_checkpoint("cp-123", True, "LGTM")
        assert result["status"] == "ok"
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"] == {"approved": True, "feedback": "LGTM"}
