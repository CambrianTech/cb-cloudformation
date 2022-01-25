from argparse import ArgumentError
import click
import troposphere as ts


@click.command()
@click.argument("template-type", type=click.Choice(["backend", "frontendpipeline"]))
@click.argument("output-path", type=click.Path(dir_okay=False))
def main(template_type, output_path):
    if template_type == "backend":
        from backend.backend import create_backend
        template = ts.Template("Cambrian image processing backend")
        create_backend(template)
    elif template_type == "frontendpipeline":
        from frontendpipeline.frontendpipeline import create_frontendpipeline
        template = ts.Template("Frontend deployment pipeline with approval process")
        create_frontendpipeline(template)
    else:
        raise ArgumentError("Unknown template type %s." % template_type)
    
    template_yaml = template.to_yaml()
    with open(output_path, "w", encoding="utf-8") as output_file:
        output_file.write(template_yaml)


if __name__ == "__main__":
    main()