import streamlit as st
import requests
import re
from datetime import datetime

# Configure page
st.set_page_config(page_title="iPA Search", layout="wide")
st.title("iPA Search")

# Create search interface
with st.container():
    with st.form("search_form"):
        col1, col2, col3, col4, col5 = st.columns([3, 1, 1, 1, 1])
        with col1:
            query = st.text_input(
                "Search query",
                placeholder="Enter your search terms...",
                key="query_input",
            )
        with col2:
            store = st.selectbox("Data store", ["plain", "fhir"])
        with col3:
            index_choices = ["ipa"]
            index_choice = st.selectbox(
                "Index",
                index_choices,
                accept_new_options=True,
            )

            # Patient ID Input
            patient_id_choices = ["mock-data"]
            patient_id = st.selectbox(
                "Patient ID",
                patient_id_choices,
                accept_new_options=True,
            )

        with col4:
            try:
                methods = requests.get(f"http://localhost:8000/{store}/search").json()
                method = st.selectbox("Search method", methods)

            except requests.ConnectionError:
                st.error("Could not fetch methods from backend")
                st.stop()
        with col5:
            st.write("\n")
            search_clicked = st.form_submit_button("Search")

# When search is submitted (either via enter or button)
if search_clicked:
    if not query:
        st.warning("Please enter a search query first")
        st.stop()
    with st.spinner("Searching through patient record..."):
        try:
            # Build URL depending on store type
            if store == "fhir":
                if not patient_id:
                    st.error("Please enter a Patient ID for FHIR searches.")
                    st.stop()
                url = f"http://localhost:8000/fhir/search/{index_choice}/{patient_id}"
            else:
                url = f"http://localhost:8000/plain/search/{index_choice}/{patient_id}"

            response = requests.post(
                url,
                json={"search": {"method": method, "query": query}},
            )
            response.raise_for_status()
            results = response.json()

            if not results.get("os_results", {}).get("hits", {}).get("hits"):
                st.warning("No results found. Try different search terms.")
            else:
                st.subheader(
                    f"Found {len(results['os_results']['hits']['hits'])} relevant results:"
                )

                # Display results in ordered cards
                if results.get("explanation"):
                    st.caption(f"Explanation: {results['explanation']}")
                for i, hit in enumerate(results["os_results"]["hits"]["hits"], 1):
                    source = hit.get("_source", {})
                    with st.expander(
                        f"Result #{i}: {source.get('filename', 'Untitled')}",
                        expanded=True,
                    ):
                        cols = st.columns([2, 3, 2])
                        with cols[0]:
                            # st.markdown(f"**File name**:\n{source.get('filename', 'N/A')}")
                            st.markdown(f"**Path**:\n`{source.get('path', 'N/A')}`")
                            st.markdown(
                                f"**Last indexed**:\n{datetime.fromtimestamp(source.get('timestamp', 0)).strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                        with cols[1]:
                            full_content = source.get("content", "N/A")

                            # Get highlighted content from OpenSearch or fallback to original
                            highlighted_content = hit.get("highlight", {}).get(
                                "content", [full_content]
                            )[0]

                            # Find first highlight position for preview
                            first_em = highlighted_content.find("<em>")
                            if first_em != -1:
                                # Show context around first highlight (300 chars before/after)
                                start = max(0, first_em - 300)
                                end = min(
                                    len(highlighted_content),
                                    first_em + 300 + len("<em></em>"),
                                )
                                preview_content = highlighted_content[start:end]
                            else:
                                # Fallback to first 500 chars if no highlights
                                preview_content = highlighted_content[:500]

                            # Clean up any broken <em> tags at the start/end of preview
                            preview_content = re.sub(
                                r"^[^<]*</em>", "", preview_content
                            )  # Remove closing tags at start
                            preview_content = re.sub(
                                r"<em>[^>]*$", "", preview_content
                            )  # Remove opening tags at end
                            preview_content = (
                                preview_content.strip()
                            )  # Clean whitespace

                            # Convert emphasis tags to Streamlit markdown highlighting
                            styled_content = highlighted_content.replace(
                                "<em>", ":blue-background["
                            ).replace("</em>", "]")
                            styled_preview = preview_content.replace(
                                "<em>", ":blue-background["
                            ).replace("</em>", "]")

                            # Display content with highlights
                            with st.expander(f"{styled_preview}", expanded=False):
                                st.markdown(styled_content)
                        with cols[2]:
                            st.markdown("The PDF might be shown here some day.")

        except requests.ConnectionError:
            st.error("Could not connect to search API. Is the backend service running?")
        except Exception as e:
            st.error(f"Search failed: {str(e)}")

elif search_clicked and not query:
    st.warning("Please enter a search query first")
