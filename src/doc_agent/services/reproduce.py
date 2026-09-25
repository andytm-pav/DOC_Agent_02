"""Document reproduction service."""

from pathlib import Path

from doc_agent.db.session import get_session
from doc_agent.db.models import File
from doc_agent.subagents.reconstructor_agent import ReconstructorAgent


async def reproduce_document(file_id: int, target_format: str) -> str:
    """Reproduce a document in the target format."""
    with get_session() as session:
        file = session.query(File).filter(File.id == file_id).first()
        if not file:
            raise ValueError(f"File not found: {file_id}")

        # Load tree
        tree_path = Path(file.stored_path).parent / "tree.json"
        if not tree_path.exists():
            raise ValueError(f"Tree not found for file: {file_id}")

        # Output path
        output_dir = Path(file.stored_path).parent / "reproduced"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = str(output_dir / f"reproduced.{target_format}")

        reconstructor = ReconstructorAgent()
        return await reconstructor.run(str(tree_path), target_format, output_path)
