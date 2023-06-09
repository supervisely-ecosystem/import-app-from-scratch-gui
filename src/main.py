import os

import supervisely as sly
from dotenv import load_dotenv
from supervisely.app import DialogWindowError
from supervisely.app.widgets import (
    Button,
    Card,
    Checkbox,
    Container,
    Input,
    ProjectThumbnail,
    SelectWorkspace,
    SlyTqdm,
    TeamFilesSelector,
    Text,
)

# Load ENV variables for debug, has no effect in production
IS_PRODUCTION = sly.is_production()
if IS_PRODUCTION is True:
    load_dotenv("advanced.env")
    STORAGE_DIR = sly.app.get_data_dir()
else:
    load_dotenv("local.env")

load_dotenv(os.path.expanduser("~/supervisely.env"))

# Get ENV variables
TEAM_ID = sly.env.team_id()
WORKSPACE_ID = sly.env.workspace_id()
PATH_TO_FOLDER = sly.env.folder(raise_not_found=False)

# create api object to communicate with Supervisely Server
api = sly.Api.from_env()


# Create GUI
# Step 1: Import Data
if IS_PRODUCTION is True:
    tf_selector = TeamFilesSelector(
        team_id=TEAM_ID, multiple_selection=False, max_height=300, selection_file_type="folder"
    )
    data_card = Card(
        title="Select Data",
        description="Check folder in File Browser to import it",
        content=tf_selector,
    )
else:
    data_text = Text()
    if PATH_TO_FOLDER is None:
        data_text.set("Please, specify path to folder with data in local.env file.", "error")
    else:
        if os.path.isdir(PATH_TO_FOLDER):
            data_text.set(f"Folder with data: '{PATH_TO_FOLDER}'", "success")
        else:
            data_text.set(f"Folder with data: '{PATH_TO_FOLDER}' not found", "error")
    data_card = Card(
        title="Local Data", description="App was launched in development mode.", content=data_text
    )

# Step 2: Settings
remove_source_files = Checkbox("Remove source files after successful import", checked=True)
settings_card = Card(
    title="Settings", description="Select import settings", content=remove_source_files
)

# Step 3: Create Project
ws_selector = SelectWorkspace(default_id=WORKSPACE_ID, team_id=TEAM_ID)
output_project_name = Input(value="My Project")
project_creator = Container(widgets=[ws_selector, output_project_name])
project_card = Card(
    title="Create Project",
    description="Select destination team, workspace and enter project name",
    content=project_creator,
)
# Step 4: Output
start_import_btn = Button(text="Start Import")
output_project_thumbnail = ProjectThumbnail()
output_project_thumbnail.hide()
output_text = Text()
output_text.hide()
output_progress = SlyTqdm()
output_progress.hide()
output_container = Container(
    widgets=[output_project_thumbnail, output_text, output_progress, start_import_btn]
)
output_card = Card(
    title="Output", description="Press button to start import", content=output_container
)
# create app object
layout = Container(widgets=[data_card, settings_card, project_card, output_card])
app = sly.Application(layout=layout)


@start_import_btn.click
def start_import():
    try:
        data_card.lock()
        settings_card.lock()
        project_card.lock()
        output_text.hide()
        project_name = output_project_name.get_value()
        if project_name is None or project_name == "":
            output_text.set(text="Please, enter project name", status="error")
            output_text.show()
            return
        # download folder from Supervisely Team Files to local storage if debugging in production mode
        PATH_TO_FOLDER = tf_selector.get_selected_paths()
        if len(PATH_TO_FOLDER) > 0:
            PATH_TO_FOLDER = PATH_TO_FOLDER[0]
            # specify local path to download
            local_data_path = os.path.join(
                STORAGE_DIR, os.path.basename(PATH_TO_FOLDER).lstrip("/")
            )
            # download file from Supervisely Team Files to local storage
            api.file.download_directory(
                team_id=TEAM_ID, remote_path=PATH_TO_FOLDER, local_save_path=local_data_path
            )
        else:
            output_text.set(
                text="Please, specify path to folder in Supervisely Team Files", status="error"
            )
            output_text.show()
            return
        project = api.project.create(
            workspace_id=WORKSPACE_ID, name=project_name, change_name_if_conflict=True
        )
        dataset = api.dataset.create(
            project_id=project.id, name="ds0", change_name_if_conflict=True
        )
        output_progress.show()

        images_names = []
        images_paths = []
        for file in os.listdir(local_data_path):
            file_path = os.path.join(local_data_path, file)
            images_names.append(file)
            images_paths.append(file_path)

        with output_progress(total=len(images_paths)) as pbar:
            for img_name, img_path in zip(images_names, images_paths):
                try:
                    # upload image into dataset on Supervisely server
                    info = api.image.upload_path(
                        dataset_id=dataset.id, name=img_name, path=img_path
                    )
                    sly.logger.trace(f"Image has been uploaded: id={info.id}, name={info.name}")
                except Exception as e:
                    sly.logger.warn("Skip image", extra={"name": img_name, "reason": repr(e)})
                finally:
                    # update progress bar
                    pbar.update(1)

        # remove source files from Supervisely Team Files if checked
        if remove_source_files.is_checked():
            api.file.remove_dir(TEAM_ID, PATH_TO_FOLDER)

        # hide progress bar after import
        output_progress.hide()

        # update project info for thumbnail preview
        project = api.project.get_info_by_id(project.id)
        output_project_thumbnail.set(info=project)
        output_project_thumbnail.show()
        output_text.set(text="Import is finished", status="success")
        output_text.show()
        start_import_btn.disable()
        sly.logger.info(f"Result project: id={project.id}, name={project.name}")
    except Exception as e:
        data_card.unlock()
        settings_card.unlock()
        project_card.unlock()
        raise DialogWindowError(title="Import error", description=f"Error: {e}")
