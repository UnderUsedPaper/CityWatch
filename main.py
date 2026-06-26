import streamlit as st
import ollama
import json
import requests
import base64
from PIL import Image

def convert_image_to_base64(uploaded_file):
    # Open with PIL and resize to a reasonable resolution for AI vision
    img = Image.open(uploaded_file)
    img.thumbnail((800, 800)) # Keeps aspect ratio but limits max width/height to 800px
    
    import io
    buffered = io.BytesIO()
    img.save(buffered, format="JPEG")
    img_bytes = buffered.getvalue()
    
    return base64.b64encode(img_bytes).decode("utf-8")

def analyze_hazard_with_ai(uploaded_file, description):
    """
    Sends the uploaded image and optional description to the local
    Gemma 4 model through Ollama.

    Returns the AI's response as a Python dictionary.
    """

    image_base64 = convert_image_to_base64(uploaded_file)

    if description.strip():
        resident_information = description
    else:
        resident_information = "The resident did not provide a description."

    prompt = f"""
You are City Watch, an AI system that analyzes photographs of urban hazards.

A city resident uploaded a photograph of a possible public infrastructure
or safety problem.

Resident description:
{resident_information}

Carefully inspect the image.

Identify the most likely issue, such as:

- broken streetlight
- leaking or damaged fire hydrant
- pothole
- street flooding
- fallen tree
- blocked sidewalk
- damaged traffic sign
- exposed electrical equipment
- overflowing garbage
- damaged road
- another city infrastructure problem

Return only valid JSON using exactly this format:

{{
    "issue_identification": "Specific name of the issue",
    "danger_level": "Low, Medium, High, or Critical",
    "confidence": 85,
    "visible_evidence": "What you can actually see in the image",
    "safety_recommendation": "How residents should avoid the hazard",
    "appropriate_authority": "The city department that should respond",
    "recommended_city_action": "What the authority should do",
    "reasoning": "Why you assigned this danger level"
}}

Rules:

1. Use the image as the main source of evidence.
2. Do not invent hazards that are not visible.
3. If the image is unclear, say that confidence is low.
4. Confidence must be an integer from 0 to 100.
5. Critical should only be used for an immediate danger to life.
6. Never tell residents to touch or personally repair dangerous infrastructure.
7. Return JSON only. Do not include Markdown or additional commentary.
"""

    ollama_url = "http://127.0.0.1:11434/api/chat"

    request_data = {
        "model": "llama3.2-vision",  # <--- Change this line here
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_base64]
            }
        ],
        "stream": False,
        "format": "json",
        "options": {
            "temperature": 0.2
        }
    }

    try:
        response = requests.post(
            ollama_url,
            json=request_data,
            timeout=180
        )

        print("Status code:", response.status_code)
        print("Response text:", response.text)

        st.write("Status code:", response.status_code)
        st.write("Response:", response.text)

        return

        ollama_response = response.json()

        ai_text = ollama_response["message"]["content"]

        analysis = json.loads(ai_text)

        return analysis

    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            "City Watch could not connect to Ollama. "
            "Make sure Ollama is installed and running."
        )

    except requests.exceptions.Timeout:
        raise RuntimeError(
            "The AI analysis took too long. Try again or use a smaller image."
        )

    except requests.exceptions.HTTPError:
        st.write(response.text)  # show the actual Ollama error
        raise

    except json.JSONDecodeError:
        raise RuntimeError(
            "Gemma returned an invalid response. Please try analyzing the image again."
        )

    except KeyError:
        raise RuntimeError(
            "The Ollama response did not contain the expected AI message."
        )



# Configure the browser tab and page layout
st.set_page_config(
    page_title="CityWatch",
    page_icon="🏙️",
    layout="centered"
)


# App title and description
st.title("CityWatch")

st.write(
    """
    City Watch allows residents to photograph urban hazards and submit them
    for AI analysis.

    Upload a picture of a local problem such as a broken streetlight,
    leaking fire hydrant, fallen tree, pothole, flooding, or blocked sidewalk.
    """
)

st.warning(
    "City Watch is a prototype and is not an emergency service. "
    "For an immediate danger, move away from the area and contact emergency services."
)

st.header("1. Upload a photo")

uploaded_photo = st.file_uploader(
    "Take or upload a clear photo of the city hazard",
    type=["jpg", "jpeg", "png", "webp"],
    help="Supported file types: JPG, JPEG, PNG, and WEBP."
)


# Display the photo after the user uploads it
if uploaded_photo is not None:
    try:
        image = Image.open(uploaded_photo)

        st.image(
            image,
            caption="Uploaded city hazard",
            use_container_width=True
        )

        st.success("Photo uploaded successfully.")

    except Exception as error:
        st.error(f"The image could not be opened: {error}")


st.header("2. Describe the issue")

description = st.text_area(
    "Optional description",
    placeholder=(
        "Example: The fire hydrant has been leaking into the road "
        "for about 20 minutes."
    ),
    height=120,
    help=(
        "The description is optional, but it may help the AI better "
        "understand what is happening."
    )
)

st.header("3. Add report details")

location = st.text_input(
    "Location",
    placeholder="Example: 5th Street and Pine Avenue"
)

start_time = st.text_input(
    "When did the problem start?",
    placeholder="Example: Around 3:15 PM or approximately 20 minutes ago"
)


# Submit button
submit_button = st.button(
    "Continue to AI analysis",
    type="primary",
    use_container_width=True
)


if submit_button:
    if uploaded_photo is None:
        st.error("Please upload a photo before continuing.")

    elif not location.strip():
        st.error("Please enter the location of the issue.")

    else:
        st.success("Your hazard report is ready for AI analysis.")

        st.subheader("Submitted information")

        st.write(f"**Location:** {location}")

        if start_time.strip():
            st.write(f"**Reported start time:** {start_time}")
        else:
            st.write("**Reported start time:** Not provided")

        if description.strip():
            st.write(f"**Description:** {description}")
        else:
            st.write("**Description:** No description provided")

        st.info(
            "In Part 2, this photo and information will be sent to the AI "
            "to identify the issue and estimate its danger level."
        )
        st.write(analyze_hazard_with_ai(uploaded_photo, description))