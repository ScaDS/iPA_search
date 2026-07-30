import json
import requests
from ipa_backend.config import FHIR_Settings
from loguru import logger
from fastapi import HTTPException, status
from pathlib import Path


def get_fhir_headers(fhir_settings: FHIR_Settings, content_type: bool = False) -> dict:
    """
    Build FHIR HTTP headers including authentication.

    Args:
        fhir_settings: FHIR configuration and authentication settings.
        content_type: Whether to include the Content-Type header.

    Returns:
        Dictionary containing HTTP headers for FHIR requests.
    """
    token = fhir_settings.get_access_token().get_secret_value()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/fhir+json",
    }
    if content_type:
        headers["Content-Type"] = "application/fhir+json"
    return headers


def test_fhir_connection(fhir_settings: FHIR_Settings):
    """
    Test connectivity to the FHIR server using the metadata endpoint.

    Args:
        fhir_settings: FHIR configuration and authentication settings.

    Raises:
        requests.exceptions.RequestException:
        If the FHIR server cannot be reached.
    """
    headers = get_fhir_headers(fhir_settings)

    metadata_url = f"{fhir_settings.MEDPLUM_BASE_URL}/metadata"
    try:
        response = requests.get(metadata_url, headers=headers, timeout=10)
        response.raise_for_status()
        logger.info(f"FHIR connection OK to {fhir_settings.MEDPLUM_BASE_URL}")
    except requests.exceptions.RequestException as e:
        logger.error(f"FHIR connection test failed: {e}")
        raise


def load_fhir_bundles(folder_path: Path) -> list[dict]:
    """
    Load all FHIR bundles from JSON files in a directory.

    Each file is expected to contain a FHIR Bundle. Files that do not contain a
    Bundle are skipped and a warning is logged.

    Args:
        folder_path: Directory containing FHIR JSON files.

    Returns:
        List of FHIR bundles.
    """

    path = Path(folder_path)
    bundles = []

    for file in path.glob("*.json"):
        with open(file, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)

                if data.get("resourceType") == "Bundle":
                    bundles.append(data)
                else:
                    logger.warning(
                        f"Skipping {file.name}: not a Bundle "
                        f"(resourceType={data.get('resourceType')})"
                    )

            except Exception as e:
                logger.error(f"Error reading file {file}: {e}")

    logger.info(f"Loaded {len(bundles)} bundles from {path}")
    return bundles


SYNTHEA_ID_SYSTEM = "urn:synthea:uuid"


def normalize_bundle_for_idempotency(bundle: dict) -> dict:
    """
    Ensure each bundle entry has an idempotent request.

    Medplum rejects ``PUT`` to non-existent UUIDs with 404 (PUT is not
    create-or-update here), so we cannot rely on ``PUT ResourceType/id``
    for idempotency. Instead we use ``POST`` + ``ifNoneExist`` based on a
    stable identifier.

    Rules, in order:
    1. Entries without a ``resource`` body or ``resourceType`` are dropped.
    2. For each remaining entry:
       - If the request has no ``ifNoneExist`` and the resource has no
         ``identifier`` but has ``resource.id``, inject an identifier
         with system ``urn:synthea:uuid`` so the entry can be deduplicated.
       - If the request is ``POST`` and has no ``ifNoneExist``, add one
         based on the resource's first identifier so re-uploads don't
         create duplicates.
       - Existing ``request`` fields and identifiers are otherwise left
         untouched.

    The bundle is modified in place and also returned for convenience.
    """
    kept = []
    skipped = 0
    preserved = 0
    injected_identifier = 0
    added_if_none_exist = 0
    for entry in bundle.get("entry", []):
        resource = entry.get("resource")
        if not resource:
            logger.warning(
                f"Dropping bundle entry without resource body "
                f"(fullUrl={entry.get('fullUrl')})"
            )
            skipped += 1
            continue
        resource_type = resource.get("resourceType")
        if not resource_type:
            logger.warning(
                f"Dropping bundle entry without resourceType "
                f"(fullUrl={entry.get('fullUrl')})"
            )
            skipped += 1
            continue

        resource_id = resource.get("id")
        request = entry.get("request")
        if request is None:
            request = {"method": "POST", "url": resource_type}
            entry["request"] = request

        has_if_none_exist = "ifNoneExist" in request
        identifiers = resource.setdefault("identifier", [])

        if not has_if_none_exist and not identifiers and resource_id:
            identifiers.append({"system": SYNTHEA_ID_SYSTEM, "value": resource_id})
            injected_identifier += 1

        if request.get("method") == "POST" and not has_if_none_exist and identifiers:
            first = identifiers[0]
            system = first.get("system", "")
            value = first.get("value", "")
            if system and value:
                request["ifNoneExist"] = f"identifier={system}|{value}"
                added_if_none_exist += 1
            else:
                preserved += 1
        else:
            preserved += 1

        kept.append(entry)

    bundle["entry"] = kept
    if skipped:
        logger.info(f"Skipped {skipped} unprocessable bundle entries")
    if preserved:
        logger.info(f"Preserved {preserved} entries unchanged")
    if injected_identifier:
        logger.info(f"Injected {injected_identifier} synthetic identifiers")
    if added_if_none_exist:
        logger.info(f"Added {added_if_none_exist} ifNoneExist clauses")
    return bundle


def post_fhir_bundle(bundle: dict, fhir_settings: FHIR_Settings) -> dict:
    """
    Submit a single FHIR bundle to the Medplum server.

    Args:
        bundle: FHIR bundle (transaction or batch).
        fhir_settings: FHIR configuration and authentication settings.

    Returns:
        JSON response returned by the FHIR server.

    Raises:
        HTTPException: If the transport-level request fails.
    """

    headers = get_fhir_headers(fhir_settings, content_type=True)
    url = fhir_settings.MEDPLUM_BASE_URL

    try:
        response = requests.post(
            url,
            headers=headers,
            json=bundle,
            timeout=60,
        )
        response.raise_for_status()
        logger.info("FHIR bundle successfully posted")
        return response.json()

    except requests.exceptions.RequestException as e:
        logger.error(f"FHIR bundle upload failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FHIR bundle upload failed: {str(e)}",
        )


def upload_bundles_to_fhir(bundles: list[dict], fhir_settings: FHIR_Settings) -> dict:
    """
    Upload a list of FHIR bundles to Medplum sequentially.

    Each bundle is normalized for idempotent uploads and submitted one after
    another. Per-resource results are collected from the FHIR transaction
    response and aggregated into a summary.

    Args:
        bundles: List of FHIR bundles to upload.
        fhir_settings: FHIR configuration and authentication settings.

    Returns:
        Summary dict with bundle-level and per-resource results:
        bundles_uploaded, bundles_failed, resources_uploaded,
        resources_failed, details.
    """

    bundles_uploaded = 0
    bundles_failed = 0
    resources_uploaded = 0
    resources_failed = 0
    details = []

    for bundle_idx, bundle in enumerate(bundles):
        requested = [
            {
                "resourceType": (e.get("resource") or {}).get("resourceType"),
                "id": (e.get("resource") or {}).get("id"),
                "fullUrl": e.get("fullUrl"),
            }
            for e in bundle.get("entry", [])
        ]

        normalize_bundle_for_idempotency(bundle)

        try:
            response = post_fhir_bundle(bundle, fhir_settings)
        except HTTPException as e:
            bundles_failed += 1
            details.append(
                {
                    "bundle_index": bundle_idx,
                    "status": "transport_error",
                    "detail": e.detail,
                    "resources": [],
                }
            )
            logger.error(f"Bundle {bundle_idx} failed at transport level: {e.detail}")
            continue

        bundles_uploaded += 1

        response_entries = response.get("entry", [])
        bundle_resources = []

        for req_info, resp_entry in zip(requested, response_entries):
            entry_response = resp_entry.get("response", {})
            status_code = entry_response.get("status")
            location = entry_response.get("location", "")

            resource_type = req_info["resourceType"]
            resource_id = req_info["id"]
            if location:
                parts = location.split("/")
                if len(parts) >= 2 and parts[1] and parts[1] != "_history":
                    resource_type = resource_type or parts[0]
                    resource_id = resource_id or parts[1]

            if status_code and status_code.startswith("2"):
                resources_uploaded += 1
            else:
                resources_failed += 1
                logger.warning(
                    f"Bundle {bundle_idx} entry failed: "
                    f"{resource_type}/{resource_id} -> {status_code}"
                )

            bundle_resources.append(
                {
                    "resourceType": resource_type,
                    "id": resource_id,
                    "status": status_code,
                }
            )

        if len(response_entries) > len(requested):
            logger.warning(
                f"Bundle {bundle_idx} returned {len(response_entries)} entries "
                f"for {len(requested)} requests"
            )
            for resp_entry in response_entries[len(requested) :]:
                er = resp_entry.get("response", {})
                bundle_resources.append(
                    {
                        "resourceType": None,
                        "id": None,
                        "status": er.get("status"),
                    }
                )

        details.append(
            {
                "bundle_index": bundle_idx,
                "status": "uploaded",
                "resources": bundle_resources,
            }
        )

    summary = {
        "bundles_uploaded": bundles_uploaded,
        "bundles_failed": bundles_failed,
        "resources_uploaded": resources_uploaded,
        "resources_failed": resources_failed,
        "details": details,
    }

    logger.info(f"FHIR upload summary: {summary}")
    return summary


def search_resources_fhir(
    fhir_settings: FHIR_Settings, search_term: str, patient_id: str
) -> list[dict]:
    """
    Search resources within a patient's $everything bundle.
    The function retrieves all resources associated with a patient
    and performs a case-insensitive text search across all resources.

    Args:
        fhir_settings: FHIR configuration and authentication settings.
        search_term: Text to search for.
        patient_id: Patient identifier used for the $everything query.

    Returns:
        List of matching FHIR resources.

    Raises:
        ValueError: If no patient ID is provided.
    """
    headers = get_fhir_headers(fhir_settings)

    # Patient-ID needs to be provided for $everything search, otherwise it will fail
    if not patient_id:
        raise ValueError("Patient ID is required for $everything search")

    base_url = fhir_settings.MEDPLUM_BASE_URL

    url = f"{base_url}/Patient/{patient_id}/$everything"

    # Load Bundle
    try:
        response = requests.get(url, headers=headers, timeout=60)
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else None
        if status_code == 404:
            logger.warning(f"Patient not found in Medplum: {patient_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Patient not found: {patient_id}",
            )
        logger.error(f"FHIR $everything failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FHIR $everything failed: {str(e)}",
        )
    except requests.exceptions.RequestException as e:
        logger.error(f"FHIR $everything failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"FHIR $everything failed: {str(e)}",
        )

    bundle = response.json()

    # Extract resources
    all_resources = []
    if bundle.get("resourceType") == "Bundle":
        for entry in bundle.get("entry", []):
            res = entry.get("resource")
            if res:
                all_resources.append(res)

    # Search for ResourceTypes and collect different types
    resource_types = {r["resourceType"] for r in all_resources}

    logger.info(f"Found resourceTypes: {resource_types}")

    # Search in whole bundle
    lower_search = search_term.lower()
    matching_resources = []

    for res in all_resources:
        if lower_search in str(res).lower():
            matching_resources.append(res)

    logger.info(
        f"Found {len(matching_resources)} matching resources for '{search_term}'"
    )

    return matching_resources
