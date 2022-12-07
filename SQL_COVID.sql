

-- Covid 19 Data Exploration 


SELECT *
FROM SQL_Project_COVID..CovidDeaths
ORDER BY 3,4


SELECT *
FROM SQL_Project_COVID..CovidVaccinations
ORDER BY 3,4


-- Main Data 


SELECT Location, date, total_cases, new_cases, total_deaths, population
FROM SQL_Project_COVID..CovidDeaths
WHERE continent is not null 
ORDER BY 1,2


-- Total Cases vs Total Deaths
-- Likelihood of dying if you contract covid in Georgia


SELECT Location, date, total_cases,total_deaths, (total_deaths/total_cases)*100 as Death_Percentage
FROM SQL_Project_COVID..CovidDeaths
WHERE location like '%Georgia%'
and continent is not null 
ORDER BY 1,2 DESC

-- Countries with Highest Death Count per Population

Select Location, MAX(cast(Total_deaths as bigint)) as TotalDeathCount
FROM SQL_Project_COVID..CovidDeaths
WHERE continent is not null 
GROUP BY Location
ORDER BY TotalDeathCount desc

-- Countries with Highest Infection Rate compared to Population

SELECT location, population, MAX(total_cases) as Highest_Infection,MAX((total_cases/population)*100) as infecction_Rate
FROM SQL_Project_COVID..CovidDeaths
WHERE continent is not null
GROUP BY location, population
ORDER BY 4 DESC


-- Infection Rate compared to Population in Georgia

SELECT location, population, MAX(total_cases) as Highest_Infection,MAX((total_cases/population)*100) as infecction_Rate
FROM SQL_Project_COVID..CovidDeaths
WHERE location = 'Georgia'
GROUP BY location,population


-- Total Population vs Vaccinations

SELECT dea.continent, dea.location, dea.date, dea.population, 
SUM(convert(bigint,vac.new_vaccinations)) over (partition by dea.location) as total_vaccinations
FROM SQL_Project_COVID..CovidDeaths as dea
Join SQL_Project_COVID..CovidVaccinations vac
	On dea.location = vac.location
	and dea.date = vac.date
WHERE dea.continent is not null
ORDER BY 2,3



-- Power BI Queries

WITH casevsdeath (continent,total_cases_continent,total_deaths_continent)

as

(
SELECT continent, MAX(cast(total_cases as bigint)) as total_cases_continent, MAX(cast(total_deaths as bigint)) as total_deaths_continent
FROM SQL_Project_COVID..CovidDeaths
WHERE continent is not null
GROUP BY continent
)

SELECT *, (cast(total_deaths_continent as float)/cast(total_cases_continent as float)) as death_rate
FROM casevsdeath



--Total Death vs Vaccinations




SELECT dea.continent, dea.location,  max(cast(dea.total_deaths as bigint)) over (partition by dea.location) as total_death_country,
MAX(convert(bigint,vac.people_fully_vaccinated)) over (partition by dea.location ) as total_vaccinations
FROM SQL_Project_COVID..CovidDeaths as dea
join SQL_Project_COVID..CovidVaccinations vac
	On dea.location = vac.location
	and dea.date = vac.date
WHERE dea.continent is not null





-- Georgia


SELECT location,sum(cast(new_cases as int)) as total_cases ,sum(cast(new_deaths as int)) as total_deaths
FROM SQL_Project_COVID..CovidDeaths 
WHERE location = 'Georgia' and YEAR(date) = '2021' 
GROUP BY location,MONTH(date)





SELECT *
FROM SQL_Project_COVID..CovidVaccinations
WHERE location = 'Georgia'
ORDER BY 3,4



-- total tests and vaccinatinos per month

SELECT location,sum(cast(new_tests as int)) as total_tests ,sum(cast(new_vaccinations as int)) as total_vaccinations
FROM SQL_Project_COVID..CovidVaccinations 
WHERE location = 'Georgia' and YEAR(date) = '2021' 
GROUP BY location,MONTH(date)
