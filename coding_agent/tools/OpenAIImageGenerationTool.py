from agency_swarm.tools import BaseTool
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from openai import AsyncOpenAI
from pathlib import Path
import asyncio
import base64
import os


load_dotenv()


class ImageGenerationRequest(BaseModel):
    """
    A single image generation request.

    This separates the inputs into a dedicated type so that agents can pass an
    array of requests, each with its own prompt, output path and size.
    """

    prompt: str = Field(
        ...,
        description="The natural language prompt describing the image to generate.",
    )
    path: str = Field(
        ...,
        description=(
            "Absolute or project-relative file path where the generated image will be "
            "saved, including the filename and extension (e.g. 'mnt/images/output.png')."
        ),
    )
    size: str = Field(
        "1024x1024",
        description=(
            "Requested image size for this generation. Common options for gpt-image-1 "
            "include '1024x1024', '1024x1536', and '1536x1024'."
        ),
    )


class OpenAIImageGenerationTool(BaseTool):
    """
    Generates one or more images using OpenAI's image generation API and saves them to disk.

    The agent should provide an array of `ImageGenerationRequest` objects via the `requests`
    field. Each request can specify its own prompt, output path, and size. All images are
    generated with low quality to optimize for speed and cost.
    """

    requests: list[ImageGenerationRequest] = Field(
        ...,
        description=(
            "List of image generation requests. Each item contains a prompt, output path, "
            "and optional size."
        ),
    )

    async def run(self) -> str:
        """
        Generate images with OpenAI's images API and save them to the requested paths.

        Steps for each request:
        1. Ensure the output directory exists.
        2. Call OpenAI's image generation endpoint with the given prompt and size.
        3. Decode the base64-encoded image returned by the API.
        4. Write the decoded bytes to the specified file path.
        After processing all requests, return a summary message listing all saved paths.
        """
        # Step 1: Initialize async OpenAI client (reads OPENAI_API_KEY from environment)
        client = AsyncOpenAI()

        # Step 2: Fire off all image generation calls in parallel
        tasks = [self._generate_single_image(client, req) for req in self.requests]
        saved_paths = await asyncio.gather(*tasks)

        return f"Generated {len(saved_paths)} image(s) and saved to: {', '.join(saved_paths)}"

    async def _generate_single_image(
        self, client: AsyncOpenAI, req: ImageGenerationRequest
    ) -> str:
        """
        Generate a single image for one request and return the final absolute path.
        """
        # Prepare output path and ensure directory exists
        output_path = Path(req.path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Call the images API for this request
        response = await client.images.generate(
            model="gpt-image-1",
            prompt=req.prompt,
            size=req.size,
            n=1,
            quality="low",
        )

        # Decode the base64 image data
        image_b64 = response.data[0].b64_json
        image_bytes = base64.b64decode(image_b64)

        # Write the image to disk
        with open(output_path, "wb") as f:
            f.write(image_bytes)

        return str(output_path)


if __name__ == "__main__":
    """
    Basic manual test for the tool.

    This will attempt to generate an image and save it to 'mnt/test-images/test.png'
    if an OPENAI_API_KEY is configured. Any exceptions are printed so the script
    exits gracefully even in environments without network access.
    """
    api_key_present = bool(os.getenv("OPENAI_API_KEY"))

    if not api_key_present:
        print("OPENAI_API_KEY is not set; skipping live image generation test.")
    else:
        try:
            test_tool = OpenAIImageGenerationTool(
                requests=[
                    ImageGenerationRequest(
                        prompt="A minimalist flat illustration of a robot writing code at a desk.",
                        path="mnt/test-images/test-1.png",
                        size="1024x1024",
                    ),
                    ImageGenerationRequest(
                        prompt="A futuristic city skyline at night in flat illustration style.",
                        path="mnt/test-images/test-2.png",
                        size="1024x1536",
                    ),
                ]
            )
            result = asyncio.run(test_tool.run())
            print(result)
        except Exception as exc:
            print(f"Image generation test failed: {exc}")


