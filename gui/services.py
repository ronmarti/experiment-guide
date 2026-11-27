from experiment.services.configuration import ConfigurationService
from experiment.services.optimization import AxOptimizer
from experiment.services.persistence import ProjectFiles
from experiment.services.prediction import PredictionController
from experiment.services.run_table import RunTableService
from experiment.services.runs import RunService
from experiment.services.validation import ProjectValidator


class AppServices:
    """Wire the services shared by components in one application session."""

    def __init__(self, optimizer: AxOptimizer | None = None) -> None:
        """Construct services using the supplied optimizer or the default Ax adapter."""
        self.optimizer = optimizer if optimizer is not None else AxOptimizer()
        validator = ProjectValidator()
        self.files = ProjectFiles(validator)
        self.configuration = ConfigurationService(validator)
        self.runs = RunService()
        self.predictions = PredictionController(self.optimizer)
        self.table = RunTableService(self.runs, self.files, self.optimizer)
