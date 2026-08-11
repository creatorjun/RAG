from typing import Protocol


class TextGeneratorPort(Protocol):
    @property
    def model_id(self) -> str:
        raise NotImplementedError

    @property
    def model_revision(self) -> str:
        raise NotImplementedError

    async def prepare(self) -> None:
        raise NotImplementedError

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        max_output_tokens: int,
    ) -> str:
        raise NotImplementedError
