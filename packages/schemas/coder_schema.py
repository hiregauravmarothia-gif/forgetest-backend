from pydantic import BaseModel, Field
from enum import Enum
from typing import Optional


class FileType(str, Enum):
    page_object = "page_object"
    spec = "spec"
    fixture = "fixture"


class GeneratedFile(BaseModel):
    type: FileType = Field(..., description="Type of generated file")
    path: str = Field(..., description="Relative path to the file")
    content: str = Field(..., description="Full file content")


class ManifestCoverage(BaseModel):
    scenario_tag: str = Field(..., description="Scenario tag (e.g., AC-1)")
    status: str = Field(..., description="Status: GENERATED, SKIPPED, or BLOCKED")
    output_file: str = Field(..., description="Path to output file")


class LocatorInventory(BaseModel):
    pass


class CoderManifest(BaseModel):
    jira_context: dict = Field(default_factory=dict, description="Jira context information")
    coverage: list[ManifestCoverage] = Field(default_factory=list, description="Coverage entries per scenario")
    locator_inventory: dict = Field(default_factory=dict, description="Inventory of locators used")
    assumptions_used: list[str] = Field(default_factory=list, description="Assumptions from Architect")


class CoderResponse(BaseModel):
    issue_key: str = Field(..., description="The Jira issue key")
    files: list[GeneratedFile] = Field(default_factory=list, description="Generated files")
    manifest: CoderManifest = Field(..., description="Manifest data")
    locator_gaps: list[str] = Field(default_factory=list, description="LOCATOR_GAP warnings")
    skipped_scenarios: list[str] = Field(default_factory=list, description="Skipped scenarios")
    timestamp: str = Field(..., description="ISO timestamp")