from pathlib import Path

from esocial_noise.reporting.input_excel import load_employees, mark_source_row_completed


def test_bibi_header_aliases_are_accepted(tmp_path: Path) -> None:
    source = tmp_path / "entrada.csv"
    source.write_text("CPF,Colaborador,CNPJ,Tipo Procuração,Agente Nocivo,Intensidade,Ano,LOG\n00123456789,Nome de teste,12.345.678/0001-90,Pessoa Jurídica,Ruído,85,02/03/2026,\n", encoding="utf-8")
    employees = load_employees(source)
    assert employees[0].cpf == "00123456789"
    assert employees[0].name == "Nome de teste"
    assert employees[0].source_row == 2
    assert employees[0].representation_type == "pessoa_juridica"
    assert employees[0].represented_document == "12345678000190"
    assert employees[0].expected_start_date == "02/03/2026"
    assert employees[0].expected_intensity == "85"


def test_profile_and_expected_values_are_accepted(tmp_path: Path) -> None:
    source = tmp_path / "entrada.csv"
    source.write_text("CNPJ,Perfil,CPF,Colaborador,Intensidade,Ano\n06.269.953/0001-36,Pessoa Juridica,36008648072,Nome de teste,80,02/03/2026\n", encoding="utf-8")
    employee = load_employees(source)[0]
    assert employee.representation_type == "pessoa_juridica"
    assert employee.expected_start_date == "02/03/2026"
    assert employee.expected_intensity == "80"


def test_completed_rows_are_ignored_and_csv_is_updated(tmp_path: Path) -> None:
    source = tmp_path / "entrada.csv"
    source.write_text(
        "CNPJ,Perfil,CPF,Intensidade,Ano,LOG,Status\n"
        "06.269.953/0001-36,Pessoa Juridica,36008648072,80,02/03/2026,,Concluido\n"
        "06.269.953/0001-36,Pessoa Juridica,36008648073,80,02/03/2026,,\n",
        encoding="utf-8",
    )
    employees = load_employees(source)
    assert [employee.cpf for employee in employees] == ["36008648073"]
    mark_source_row_completed(source, 3, no_noise=True)
    text = source.read_text(encoding="utf-8-sig")
    assert "Não há Agente de Ruído" in text
    assert text.count("Concluido") == 2
